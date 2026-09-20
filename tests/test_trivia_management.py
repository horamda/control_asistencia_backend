import datetime
import re
import sqlite3
from pathlib import Path
import pytest
from repositories import trivia_repository as repo


@pytest.fixture
def trivia_db(monkeypatch):
    db=sqlite3.connect(':memory:')
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.create_function('CONCAT',-1,lambda *args: ''.join(str(a or '') for a in args))
    db.create_function('NOW',0,lambda: '2026-09-20 12:00:00')
    db.executescript('''CREATE TABLE empleados(id INTEGER PRIMARY KEY,dni TEXT,nombre TEXT,apellido TEXT,sector_id INTEGER,activo INTEGER,legajo TEXT);
    CREATE TABLE sectores(id INTEGER PRIMARY KEY,nombre TEXT);
    CREATE TABLE auditoria(id INTEGER PRIMARY KEY,usuario_id INTEGER,accion TEXT,tabla_afectada TEXT,registro_id INTEGER);
    INSERT INTO empleados(id,dni,nombre,apellido,sector_id,activo) VALUES(10,'10','Ana','Perez',1,1),(11,'11','Luis','Gomez',1,1);
    INSERT INTO sectores VALUES(1,'Almacen');''')
    for name in ['20260524_01_trivia_operativa.sql','20260524_02_trivia_sectores_multiples.sql','20260527_01_trivia_exclusiones.sql','20260528_01_trivia_ranking_anual_exclusiones.sql','20260920_02_trivia_ranking_exclusiones.sql']:
        sql=(Path(__file__).parents[1]/'migrations'/name).read_text(encoding='utf-8-sig')
        # Only CREATE TABLE statements, never backfills for this isolated fixture.
        for statement in re.findall(r'CREATE TABLE IF NOT EXISTS .*?;',sql,re.S):
            statement=re.sub(r'--[^\n]*','',statement)
            statement=re.sub(r"ENUM\([^)]*\)",'TEXT',statement)
            statement=re.sub(r" COMMENT '[^']*'",'',statement)
            statement=statement.replace('INT AUTO_INCREMENT PRIMARY KEY','INTEGER PRIMARY KEY AUTOINCREMENT')
            statement=statement.replace(' ON UPDATE CURRENT_TIMESTAMP','')
            statement=re.sub(r'UNIQUE KEY \w+','UNIQUE',statement)
            statement=re.sub(r'^\s*(?:INDEX|KEY) [^\n]*','',statement,flags=re.M)
            statement=re.sub(r',\s*\) ENGINE=.*?;',');',statement,flags=re.S)
            statement=re.sub(r'\) ENGINE=.*?;',');',statement,flags=re.S)
            db.executescript(statement)
    db.executescript('''INSERT INTO trivias(id,titulo,fecha_inicio,fecha_fin,estado,anio) VALUES
      (1,'Primera','2026-01-01','2026-12-31','finalizada',2026),
      (2,'Segunda','2026-01-01','2026-12-31','finalizada',2026);
    INSERT INTO trivia_preguntas(id,trivia_id,texto,opcion_a,opcion_b,opcion_c,opcion_d,respuesta_correcta) VALUES(1,1,'Pregunta','A','B','C','D','A');
    INSERT INTO trivia_resultados(id,trivia_id,empleado_id,empleado_dni,fecha_inicio_participacion,fecha_finalizacion,tiempo_total_segundos,puntos_total,correctas,estado_resultado) VALUES
      (1,1,10,'10','2026-09-19','2026-09-19',10,100,10,'completado'),
      (2,1,11,'11','2026-09-19','2026-09-19',20,80,8,'completado'),
      (3,2,10,'10','2026-09-19','2026-09-19',10,50,5,'completado');
    INSERT INTO trivia_respuestas(trivia_id,pregunta_id,empleado_id,empleado_dni,respuesta_seleccionada) VALUES(1,1,10,'10','A');
    INSERT INTO trivia_notificaciones(trivia_id,empleado_id,empleado_dni,tipo) VALUES(1,10,'10','recordatorio_24h');''')
    fail={'annual':False}
    class Cursor:
        def execute(self,sql,args=()):
            if fail['annual'] and 'INSERT INTO trivia_ranking_anual' in sql: raise RuntimeError('injected failure')
            sql=sql.replace('%s','?').replace(' FOR UPDATE','')
            sql=sql.replace('ON DUPLICATE KEY UPDATE motivo=VALUES(motivo)','ON CONFLICT(trivia_id,empleado_id) DO UPDATE SET motivo=excluded.motivo')
            self.cur=db.execute(sql,args);self.rowcount=self.cur.rowcount;self.lastrowid=self.cur.lastrowid
        def fetchall(self):return [dict(r) for r in self.cur.fetchall()]
        def fetchone(self):
            row=self.cur.fetchone();return dict(row) if row else None
        def close(self):pass
    class Connection:
        def cursor(self,**kwargs):return Cursor()
        def commit(self):db.commit()
        def rollback(self):db.rollback()
        def close(self):pass
    monkeypatch.setattr(repo,'get_db',Connection)
    yield db,fail
    db.close()


def test_rank_exclusion_preserves_play_and_personal_scores(trivia_db):
    db,_=trivia_db
    repo.set_exclusion_ranking_trivia(1,10,excluir=True,usuario_id=99)
    assert [r['empleado_id'] for r in repo.get_ranking_trivia(1)]==[11]
    assert repo.get_ganador_trivia(1)['empleado_id']==11
    personal=repo.get_resultado_by_trivia_empleado(1,10)
    assert personal['fuera_ranking']==1 and personal['puntos_total']==100
    assert personal['posicion'] is None and personal['es_ganador']==0
    assert len(repo.get_historial_empleado(10))==2
    assert repo.is_empleado_excluido(1,10) is False
    annual={r['empleado_id']:r for r in repo.get_ranking_anual(2026)}
    assert annual[10]['puntos_anuales']==50 and annual[11]['puntos_anuales']==80
    assert db.execute('SELECT COUNT(*) FROM trivia_respuestas').fetchone()[0]==1
    repo.set_exclusion_ranking_trivia(1,10,excluir=False,usuario_id=99)
    assert repo.get_ganador_trivia(1)['empleado_id']==10
    assert repo.get_ranking_anual(2026)[0]['puntos_anuales']==150


def test_delete_removes_all_children_and_updates_annual(trivia_db):
    db,_=trivia_db
    repo.set_exclusion_ranking_trivia(1,11,excluir=True,usuario_id=99)
    repo.delete_trivia_completa(1,usuario_id=99)
    assert repo.get_trivia_by_id(1) is None
    assert repo.get_trivia_by_id(2)
    for table in repo._TRIVIA_CHILDREN:
        assert db.execute(f'SELECT COUNT(*) FROM {table} WHERE trivia_id=1').fetchone()[0]==0
    annual=repo.get_ranking_anual(2026)
    assert len(annual)==1 and annual[0]['empleado_id']==10 and annual[0]['puntos_anuales']==50
    assert db.execute("SELECT COUNT(*) FROM auditoria WHERE accion='delete'").fetchone()[0]==1


@pytest.mark.parametrize('operation',['delete','exclude'])
def test_failure_rolls_back_entire_operation(trivia_db,operation):
    db,fail=trivia_db
    fail['annual']=True
    with pytest.raises(RuntimeError):
        if operation=='delete':repo.delete_trivia_completa(1,usuario_id=99)
        else:repo.set_exclusion_ranking_trivia(1,10,excluir=True,usuario_id=99)
    assert repo.get_trivia_by_id(1)
    assert db.execute('SELECT COUNT(*) FROM trivia_resultados WHERE trivia_id=1').fetchone()[0]==2
    assert not repo.get_exclusiones_ranking_trivia(1)
    assert db.execute('SELECT COUNT(*) FROM auditoria').fetchone()[0]==0


def test_all_excluded_yields_no_winner(trivia_db):
    repo.set_exclusion_ranking_trivia(1,10,excluir=True,usuario_id=99)
    repo.set_exclusion_ranking_trivia(1,11,excluir=True,usuario_id=99)
    assert repo.get_ranking_trivia(1)==[] and repo.get_ganador_trivia(1) is None



def test_finalize_respects_exclusions_and_rolls_back(trivia_db):
    db, fail = trivia_db
    db.execute("UPDATE trivias SET estado='activa' WHERE id=1")
    db.commit()
    repo.set_exclusion_ranking_trivia(1, 10, excluir=True)
    fail['annual'] = True
    with pytest.raises(RuntimeError):
        repo.rebuild_competition(1, finalizar=True)
    assert repo.get_trivia_by_id(1)['estado'] == 'activa'
    assert repo.get_ganador_trivia(1) is None
    fail['annual'] = False
    repo.rebuild_competition(1, finalizar=True)
    assert repo.get_trivia_by_id(1)['estado'] == 'finalizada'
    assert repo.get_ganador_trivia(1)['empleado_id'] == 11
    assert repo.get_resultado_by_trivia_empleado(1, 10)['posicion'] is None


def test_finalize_with_no_competitors(trivia_db):
    db, _ = trivia_db
    db.execute('DELETE FROM trivia_resultados WHERE trivia_id=1')
    db.commit()
    repo.rebuild_competition(1, finalizar=True)
    assert repo.get_ganador_trivia(1) is None
    assert repo.get_ranking_anual(2026)[0]['puntos_anuales'] == 50
