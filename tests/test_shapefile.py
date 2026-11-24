import struct
import unittest
import zipfile
from io import BytesIO

from pyproj import CRS, Transformer

from app import dbfio
from app.shapefile import load_shapefile_zip


def point_shapefile(longitude: float, latitude: float) -> bytes:
    header = bytearray(100)
    struct.pack_into(">i", header, 0, 9994)
    struct.pack_into(">i", header, 24, 64)
    struct.pack_into("<2i", header, 28, 1000, 1)
    struct.pack_into("<4d", header, 36, longitude, latitude, longitude, latitude)
    struct.pack_into("<4d", header, 68, 0, 0, 0, 0)
    record = struct.pack(">2i", 1, 10) + struct.pack("<i2d", 1, longitude, latitude)
    return bytes(header) + record


def polygon_shapefile() -> bytes:
    points = [(39.0, 57.0), (40.0, 57.0), (40.0, 58.0), (39.0, 58.0), (39.0, 57.0)]
    content = (
        struct.pack("<i4d2i", 5, 39.0, 57.0, 40.0, 58.0, 1, len(points))
        + struct.pack("<i", 0)
        + b"".join(struct.pack("<2d", *point) for point in points)
    )
    header = bytearray(100)
    struct.pack_into(">i", header, 0, 9994)
    struct.pack_into(">i", header, 24, (100 + 8 + len(content)) // 2)
    struct.pack_into("<2i", header, 28, 1000, 5)
    struct.pack_into("<4d", header, 36, 39.0, 57.0, 40.0, 58.0)
    struct.pack_into("<4d", header, 68, 0, 0, 0, 0)
    return bytes(header) + struct.pack(">2i", 1, len(content) // 2) + content


def dataset_zip() -> bytes:
    archive = BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("mines.shp", point_shapefile(39.72, 57.63))
        zipped.writestr(
            "mines.dbf",
            dbfio.dumps([{"NAME": "Примерное месторождение", "MINERAL": "Железная руда"}]),
        )
    return archive.getvalue()


class ShapefileTests(unittest.TestCase):
    def test_reads_record_and_geographic_point_without_projection_file(self):
        dataset = load_shapefile_zip("mines.zip", dataset_zip())

        self.assertEqual(len(dataset.records), 1)
        record = dataset.records[0]
        self.assertEqual(record.name, "Примерное месторождение")
        self.assertEqual(record.canonical["MINERAL"], "Железная руда")
        self.assertEqual(record.geometry, {"type": "Point", "coordinates": [39.72, 57.63]})
        self.assertAlmostEqual(record.center["lat"], 57.63)
        self.assertTrue(any(".prj отсутствует" in warning for warning in dataset.warnings))

    def test_reads_archive_from_seekable_stream(self):
        dataset = load_shapefile_zip("mines.zip", BytesIO(dataset_zip()))

        self.assertEqual(len(dataset.records), 1)
        self.assertEqual(dataset.records[0].name, "Примерное месторождение")

    def test_decodes_cyrillic_dbf_field_names(self):
        dbf = bytearray(
            dbfio.dumps([{"NAME": "Участок", "MINERAL": "Золото"}])
        )
        descriptor = 32 + 2 * 32
        encoded_name = "МИНЕРАЛ".encode("cp1251")
        dbf[descriptor : descriptor + 11] = b"\x00" * 11
        dbf[descriptor : descriptor + len(encoded_name)] = encoded_name
        archive = BytesIO()
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("mines.shp", point_shapefile(39.72, 57.63))
            zipped.writestr("mines.dbf", dbf)

        dataset = load_shapefile_zip("mines.zip", archive.getvalue())

        self.assertEqual(dataset.records[0].attributes["МИНЕРАЛ"], "Золото")
        self.assertEqual(dataset.records[0].canonical["MINERAL"], "Золото")

    def test_rejects_archive_without_dbf(self):
        archive = BytesIO()
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("mines.shp", point_shapefile(39.72, 57.63))

        with self.assertRaisesRegex(ValueError, "одноимённый файл .dbf"):
            load_shapefile_zip("mines.zip", archive.getvalue())

    def test_reads_polygon_rings_for_map_display(self):
        archive = BytesIO()
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("mines.shp", polygon_shapefile())
            zipped.writestr("mines.dbf", dbfio.dumps([{"NAME": "Участок"}]))

        dataset = load_shapefile_zip("mines.zip", archive.getvalue())

        self.assertEqual(dataset.records[0].geometry["type"], "Polygon")
        self.assertEqual(len(dataset.records[0].geometry["coordinates"][0]), 5)
        self.assertAlmostEqual(dataset.records[0].center["lat"], 57.4)
        self.assertAlmostEqual(dataset.records[0].center["lon"], 39.4)

    def test_reprojects_coordinates_using_prj(self):
        x, y = Transformer.from_crs(4326, 3857, always_xy=True).transform(39.72, 57.63)
        archive = BytesIO()
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("mines.shp", point_shapefile(x, y))
            zipped.writestr("mines.dbf", dbfio.dumps([{"NAME": "Участок"}]))
            zipped.writestr("mines.prj", CRS.from_epsg(3857).to_wkt())

        dataset = load_shapefile_zip("mines.zip", archive.getvalue())

        self.assertAlmostEqual(dataset.records[0].center["lat"], 57.63, places=5)
        self.assertAlmostEqual(dataset.records[0].center["lon"], 39.72, places=5)
        self.assertEqual(dataset.warnings, [])

if __name__ == "__main__":
    unittest.main()
