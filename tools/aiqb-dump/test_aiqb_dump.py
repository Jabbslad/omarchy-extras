#!/usr/bin/env python3

import pathlib
import unittest
from importlib.machinery import SourceFileLoader


ROOT = pathlib.Path(__file__).resolve().parents[2]
AIQB_PATH = ROOT / "packaging/sc200pc-ipu75xa-config/SC200PC_KAFC917_PTL.aiqb"
IMX471_AIQB_PATH = pathlib.Path("/etc/camera/ipu75xa/IMX471_BBG803N3_PTL.aiqb")
OV13B10_AIQB_PATH = pathlib.Path("/etc/camera/ipu75xa/OV13B10_09B13_PTL.aiqb")
MODULE = SourceFileLoader(
    "aiqb_dump",
    str(ROOT / "tools/aiqb-dump/aiqb-dump.py"),
).load_module()


class AiqbDumpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.buf = AIQB_PATH.read_bytes()
        cls.root = MODULE.parse_container(cls.buf, 0, len(cls.buf))
        assert cls.root is not None
        cls.imx471_buf = IMX471_AIQB_PATH.read_bytes()
        cls.imx471_root = MODULE.parse_container(cls.imx471_buf, 0, len(cls.imx471_buf))
        assert cls.imx471_root is not None
        cls.ov13b10_buf = OV13B10_AIQB_PATH.read_bytes()
        cls.ov13b10_root = MODULE.parse_container(cls.ov13b10_buf, 0, len(cls.ov13b10_buf))
        assert cls.ov13b10_root is not None

    def decode(self, variant: int, index: int):
        record, body = MODULE._select_aiqb_record(
            self.root, self.buf, variant, index
        )
        return record, MODULE.decode_record(record.record_type, record.flags, body)

    def decode_imx471(self, variant: int, index: int):
        record, body = MODULE._select_aiqb_record(
            self.imx471_root, self.imx471_buf, variant, index
        )
        return record, MODULE.decode_record(record.record_type, record.flags, body)

    def decode_ov13b10(self, variant: int, index: int):
        record, body = MODULE._select_aiqb_record(
            self.ov13b10_root, self.ov13b10_buf, variant, index
        )
        return record, MODULE.decode_record(record.record_type, record.flags, body)

    def test_sensor_info_decoder(self) -> None:
        record, decoded = self.decode(0, 0)
        self.assertEqual((record.record_type, record.flags), (0x0066, 0x0002))
        self.assertEqual(
            decoded,
            {
                "width": 1928,
                "height": 1088,
                "format_code": 15,
                "mipi_lanes": 2,
                "bits_per_pixel": 10,
            },
        )

    def test_awb_illuminant_table_decoder(self) -> None:
        record, decoded = self.decode(0, 1)
        self.assertEqual((record.record_type, record.flags), (0x0064, 0x0003))
        assert decoded is not None
        self.assertEqual(decoded["entry_count"], 5)
        self.assertEqual(decoded["trailer_zero"], 0)
        self.assertEqual(
            [entry["illuminant_code"] for entry in decoded["entries"]],
            [4, 8, 1, 15, 2],
        )
        self.assertTrue(all(entry["exposure_like"] == 30000 for entry in decoded["entries"]))

    def test_scalar_and_float_records(self) -> None:
        _, decoded_r10 = self.decode(0, 10)
        _, decoded_r12 = self.decode(0, 12)
        _, decoded_r13 = self.decode(0, 13)
        _, decoded_r16 = self.decode(0, 16)

        assert decoded_r10 is not None
        assert decoded_r12 is not None
        assert decoded_r13 is not None
        assert decoded_r16 is not None

        self.assertEqual(decoded_r10["u16"][:3], [256, 256, 2049])
        self.assertEqual(decoded_r12["value_histogram"], {1.0: 11, 8.0: 3})
        self.assertEqual(decoded_r13["values"], [0.000818, 0.045779, 0.0, 0.0, 24.220924, 0.0])
        self.assertEqual(decoded_r16["value_u32"], 2)

    def test_r07_chromaticity_quad_summary(self) -> None:
        record, decoded = self.decode(0, 7)
        self.assertEqual((record.record_type, record.flags), (0x0066, 0x000F))
        assert decoded is not None
        self.assertEqual(decoded["header_count"], 7)
        self.assertEqual(decoded["header_mode"], 2)
        self.assertEqual(decoded["quad_count"], 83)
        self.assertEqual(decoded["anchor_quad_count"], 23)
        self.assertEqual(decoded["anchor_point_count"], 9)
        self.assertEqual(decoded["tail_quad_count"], 60)
        self.assertEqual(decoded["trailer_zero"], [0, 0])
        self.assertEqual(decoded["anchor_points"][0]["sample_count"], 3)
        self.assertEqual(decoded["anchor_points"][0]["coeff_samples"], [[489, 724], [499, 731], [478, 717]])
        self.assertEqual(decoded["anchor_points"][0]["x_norm"], 0.296818)
        self.assertEqual(decoded["anchor_points"][0]["y_norm"], 0.306523)

    def test_r11_matrix_bank_table(self) -> None:
        record, decoded = self.decode(0, 11)
        self.assertEqual((record.record_type, record.flags), (0x0065, 0x0019))
        assert decoded is not None
        self.assertEqual(decoded["bank_count"], 6)
        self.assertEqual(decoded["axis_count_hint"], 24)
        self.assertEqual(decoded["axis"][:4], [15, 30, 45, 60])
        self.assertEqual(decoded["axis"][-3:], [330, 345, 360])
        self.assertEqual(decoded["matrix_count_per_bank"], 25)
        self.assertEqual(decoded["bank_summary"][0]["header"], [0.528678, 0.683292, 0.311, 0.323, 0.0, 2.162852])
        self.assertEqual(
            decoded["bank_summary"][0]["matrix0"],
            [-1.129971, -0.032881, -0.324688, 1.937995, -0.613307, -0.129237, -0.633243, 1.76248, 2.01917],
        )
        self.assertEqual(decoded["bank_summary"][0]["matrix_last"][-1], 0.0)

    def test_imx471_matrix_bank_table_variant(self) -> None:
        record, decoded = self.decode_imx471(0, 12)
        self.assertEqual((record.record_type, record.flags), (0x0065, 0x0019))
        assert decoded is not None
        self.assertEqual(decoded["bank_count"], 5)
        self.assertEqual(decoded["axis_count_hint"], 24)
        self.assertEqual(decoded["layout"], "header100")
        self.assertEqual(decoded["header_size"], 100)
        self.assertEqual(decoded["matrix_count_per_bank"], 25)
        self.assertEqual(decoded["axis"][:5], [10, 19, 28, 38, 50])
        self.assertEqual(decoded["axis"][-3:], [337, 350, 360])
        self.assertEqual(
            decoded["bank_summary"][0]["header"],
            [0.0, 0.844847, 0.326161, 0.457, 0.411, 0.0],
        )
        self.assertEqual(
            decoded["bank_summary"][0]["matrix0"],
            [1.506859, -0.243921, -0.262938, -0.49262, 1.752205, -0.259585, -0.140725, -1.113063, 2.253788],
        )

    def test_ov13b10_main_variant_offset_and_matrix_layout(self) -> None:
        aiqbs = MODULE.get_aiqb_variants(self.ov13b10_root)
        payload, meta, records = MODULE.get_aiqb_records(self.ov13b10_buf, aiqbs[0])
        self.assertEqual(meta["records_offset"], 0x210)
        self.assertEqual(len(records), 15)
        self.assertEqual((records[0].record_type, records[0].flags), (0x0066, 0x0002))
        self.assertEqual((records[-1].record_type, records[-1].flags), (0x0064, 0x0025))

        record, decoded = self.decode_ov13b10(0, 10)
        self.assertEqual((record.record_type, record.flags), (0x0065, 0x0019))
        assert decoded is not None
        self.assertEqual(decoded["layout"], "header104")
        self.assertEqual(decoded["header_size"], 104)
        self.assertEqual(decoded["bank_count"], 6)
        self.assertEqual(decoded["axis"][:5], [15, 30, 45, 60, 75])
        self.assertEqual(decoded["bank_summary"][0]["header"], [0.884, 0.442, 0.467, 0.413, 0.0, 1.596722])
        self.assertEqual(
            decoded["bank_summary"][0]["matrix0"],
            [-0.409746, -0.186976, -0.334024, 1.785846, -0.451823, -0.290119, -1.107369, 2.397488, 1.334495],
        )

    def test_compare_summary_across_sensors(self) -> None:
        sc = MODULE.build_compare_summary(AIQB_PATH)
        imx = MODULE.build_compare_summary(IMX471_AIQB_PATH)
        ov = MODULE.build_compare_summary(OV13B10_AIQB_PATH)

        self.assertEqual(sc["sensor"], "SC202PC")
        self.assertEqual(imx["sensor"], "imx471")
        self.assertEqual(ov["sensor"], "OV13B10_2K_CAF")

        self.assertEqual(sc["r11_matrix_bank"]["layout"], "header104")
        self.assertEqual(imx["r11_matrix_bank"]["layout"], "header100")
        self.assertEqual(ov["r11_matrix_bank"]["layout"], "header104")

        self.assertEqual(sc["r07_chromaticity"]["anchor_point_count"], 9)
        self.assertEqual(imx["r07_chromaticity"]["anchor_point_count"], 9)
        self.assertEqual(ov["r10_default_gains"]["u16"], [256, 256, 2049, 0])
        self.assertEqual(sc["lsc"][0]["dims_u16"], [5, 4, 63, 47])
        self.assertEqual(imx["lsc"][0]["dims_u16"], [9, 4, 63, 47])
        self.assertEqual(ov["lsc"][0]["dims_u16"], [9, 4, 63, 47])
        self.assertEqual(sc["lsc"][0]["first_gain_f32"], 0.959169)
        self.assertEqual(imx["lsc"][0]["first_gain_f32"], 0.915189)
        self.assertEqual(ov["lsc"][0]["first_gain_f32"], 0.957745)
        self.assertTrue(sc["r11_matrix_bank"]["bank_stats"][0]["matrix_last_tail_zero"])
        self.assertFalse(imx["r11_matrix_bank"]["bank_stats"][0]["matrix_last_tail_zero"])
        self.assertTrue(ov["r11_matrix_bank"]["bank_stats"][0]["matrix_last_tail_zero"])
        self.assertEqual(sc["r11_matrix_bank"]["bank_stats"][0]["matrix0_trace"], 0.275892)
        self.assertEqual(imx["r11_matrix_bank"]["bank_stats"][0]["matrix0_trace"], 5.512852)
        self.assertEqual(ov["r11_matrix_bank"]["bank_stats"][0]["matrix0_trace"], 0.472926)
        self.assertEqual(sc["r11_matrix_bank"]["bank_stats"][0]["matrix_last_det"], -1.440255)
        self.assertEqual(imx["r11_matrix_bank"]["bank_stats"][0]["matrix_last_det"], 4.856764)
        self.assertEqual(ov["r11_matrix_bank"]["bank_stats"][0]["matrix_last_det"], -1.578218)

    def test_compare_report_builder(self) -> None:
        report = MODULE.build_compare_report([AIQB_PATH, IMX471_AIQB_PATH, OV13B10_AIQB_PATH])
        self.assertEqual(len(report), 3)
        self.assertEqual([entry["sensor"] for entry in report], ["SC202PC", "imx471", "OV13B10_2K_CAF"])
        self.assertEqual(report[0]["lsc"][0]["key"], "0x0064/0x001c")
        self.assertEqual(report[1]["r11_matrix_bank"]["layout"], "header100")
        self.assertIn("bank_stats", report[2]["r11_matrix_bank"])

    def test_laiq_small_config_family(self) -> None:
        _, decoded_r4 = self.decode(1, 4)
        _, decoded_r5 = self.decode(1, 5)
        _, decoded_r8 = self.decode(1, 8)
        _, decoded_r9 = self.decode(1, 9)
        _, decoded_r10 = self.decode(1, 10)

        assert decoded_r4 is not None
        assert decoded_r5 is not None
        assert decoded_r8 is not None
        assert decoded_r9 is not None
        assert decoded_r10 is not None

        self.assertEqual(decoded_r4["header_u16"], [2, 6554])
        self.assertEqual(decoded_r4["pairs"][:3], [[1000, 100], [65535, 6], [2000, 85]])
        self.assertEqual(decoded_r5["header_u16"], [2, 7])
        self.assertEqual(decoded_r5["pairs"][:3], [[8000, 120], [5000, 120], [2000, 114]])
        self.assertEqual(decoded_r8["nonzero_u16"], [4, 80, 100, 10, 100, 2048, 8192])
        self.assertEqual(decoded_r9["header"], [1, 12])
        self.assertEqual(decoded_r9["tail_zero"], [0, 0, 0, 0])
        self.assertEqual(decoded_r10["value_u32"], 41)


if __name__ == "__main__":
    unittest.main()
