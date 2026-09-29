import io
from datetime import datetime

import pytest
from PIL import Image
from werkzeug.datastructures import FileStorage
from services import carga_service as service


@pytest.mark.parametrize('hour,minute,second,start,end,expected', [
    (8, 4, 59, 0, 485, True), (8, 5, 0, 0, 485, False), (8, 5, 1, 0, 485, False),
    (10, 59, 59, 660, 1440, False), (11, 0, 0, 660, 1440, True),
    (23, 59, 59, 660, 1440, True), (0, 0, 0, 0, 485, True),
])
def test_time_boundaries(hour, minute, second, start, end, expected):
    assert service.in_window(datetime(2026, 9, 29, hour, minute, second), start, end) is expected


@pytest.mark.parametrize('value', ['25:00', '08:60', '', '8:05', '24:01', None])
def test_invalid_clock(value):
    with pytest.raises(service.CargaError):
        service.clock_minutes(value)


def test_end_of_day():
    assert service.clock_minutes('24:00') == 1440


def image_file():
    out = io.BytesIO()
    Image.new('RGB', (30, 30), 'red').save(out, format='PNG')
    out.seek(0)
    return FileStorage(stream=out, filename='photo.png', content_type='image/png')


def test_photos_reencoded_and_limited():
    photo = service.prepare_photos([image_file()])[0]
    with Image.open(io.BytesIO(photo['contenido'])) as image:
        assert image.format == 'JPEG'
        assert image.size == (30, 30)
    with pytest.raises(service.CargaError):
        service.prepare_photos([image_file() for _ in range(6)])
    with pytest.raises(service.CargaError):
        service.prepare_photos([FileStorage(stream=io.BytesIO(b'not a photo'), filename='fake.jpg')])


def test_oversize_photo():
    with pytest.raises(service.CargaError):
        service.prepare_photos([FileStorage(stream=io.BytesIO(b'x' * (service.MAX_PHOTO_BYTES + 1)), filename='big.jpg')])
