"""Reporte de rendimiento de produccion a partir de los logs de Railway.

Cruza los logs HTTP del edge (tiempo que ve el usuario) con el log "request"
de la app (ms, db_ms, db_queries) del deploy actual. Solo lectura.

Uso (con la CLI de Railway logueada y vinculada al servicio):
    python scripts/railway_perf_report.py [--lines 5000]
"""
import argparse
import json
import re
import shutil
import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def _railway():
    local = Path.home() / ".railway" / "bin" / "railway.exe"
    exe = str(local) if local.exists() else shutil.which("railway")
    if not exe:
        raise SystemExit("No se encontro la CLI de Railway (railway login / railway link).")
    return exe


def _run(*args):
    result = subprocess.run([_railway(), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return result.stdout


def _norm(path):
    return re.sub(r"/\d+(?=/|$)", "/{id}", path.split("?")[0])


def _pct(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * p))] if values else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lines", type=int, default=5000)
    lines = parser.parse_args().lines

    edge = []
    for line in _run("logs", "--http", "--since", "7d", "-n", str(lines)).splitlines():
        m = re.match(r"(\S+) (\w+) (\S+) (\d{3}) (\d+)ms", line)
        if m:
            edge.append({"path": _norm(m[3]), "ms": int(m[5])})

    app = []
    for line in _run("logs", "--deployment", "--json", "-n", str(lines)).splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("message") == "request" and rec.get("ms") is not None:
            app.append({"path": _norm(rec.get("path", "")), "ms": rec["ms"],
                        "db_ms": rec.get("db_ms") or 0, "q": rec.get("db_queries") or 0,
                        "t": rec.get("time") or rec.get("timestamp", "")})

    print(f"Generado {datetime.now():%Y-%m-%d %H:%M} | pedidos edge: {len(edge)} | registros app: {len(app)}")
    if edge:
        ms = [r["ms"] for r in edge]
        print(f"Usuario (edge): mediana {_pct(ms, .5)} ms | p90 {_pct(ms, .9)} ms | max {max(ms)} ms"
              f" | >3 s: {100 * sum(m > 3000 for m in ms) / len(ms):.0f}%")
    if app:
        ms = [r["ms"] for r in app]
        with_db = [r for r in app if r["q"]]
        print(f"App: mediana {_pct(ms, .5):.0f} ms | p90 {_pct(ms, .9):.0f} ms")
        if with_db:
            print(f"Base: {_pct([r['db_ms'] / r['q'] for r in with_db], .5):.1f} ms por consulta (mediana)")
        by_path = defaultdict(list)
        for r in app:
            by_path[r["path"]].append(r)
        print("\nMas lentos en la app (min 3 pedidos):")
        rows = sorted(((_pct([r["ms"] for r in rs], .5), p, rs) for p, rs in by_path.items() if len(rs) >= 3), reverse=True)
        for p50, path, rs in rows[:12]:
            print(f"  {p50:7.0f} ms  {path:50} n={len(rs):3}  consultas={_pct([r['q'] for r in rs], .5):3}"
                  f"  db={_pct([r['db_ms'] for r in rs], .5):.0f} ms")


if __name__ == "__main__":
    main()
