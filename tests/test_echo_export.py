"""Linux-runnable tests for the echo export core (no ok-script / Qt needed).

Most tests use synthetic OCR items so they run with only the standard library.
``test_real_screenshot_*`` run the real onnxocr OCR on the committed equipment
screenshot and are skipped automatically if onnxocr/opencv are not installed.
"""
import os
import unittest

from src.echo_export import mappings
from src.echo_export.ocr_items import OcrItem, from_onnxocr
from src.echo_export.parser import is_equipment_page, parse_equipment_frame
from src.echo_export.recorder import EchoRecorder

W, H = 5118, 2092
IMAGES = os.path.join(os.path.dirname(__file__), "images")


def item(text, nx, ny):
    """Build an OcrItem whose center is at (nx, ny) of a 5118x2092 frame."""
    cx, cy = nx * W, ny * H
    hw, hh = 60, 20
    return OcrItem(text, int(cx - hw), int(cy - hh), int(cx + hw), int(cy + hh), W, H)


def spearback_items():
    """OCR items mirroring echo_enhance2.png (the equipment page, 箭簇熊)."""
    return [
        item("声骸推荐", 0.691, 0.044),
        item("简述", 0.822, 0.044),
        item("箭簇熊", 0.836, 0.138),
        item("+25", 0.943, 0.141),
        item("COST 3", 0.837, 0.177),
        item("湮灭伤害加成", 0.840, 0.224), item("30.0%", 0.943, 0.224),
        item("攻击", 0.839, 0.252), item("100", 0.952, 0.258),
        item("暴击", 0.839, 0.292), item("9.3%", 0.945, 0.288),
        item("生命", 0.841, 0.326), item("8.6%", 0.944, 0.326),
        item("共鸣解放伤害加成", 0.842, 0.357), item("11.6%", 0.941, 0.359),
        item("暴击伤害", 0.841, 0.393), item("13.8%", 0.941, 0.393),
        item("普攻伤害加成", 0.849, 0.422), item("7.1%", 0.945, 0.427),
        item("声骸技能", 0.836, 0.466),
        item("合鸣效果", 0.836, 0.573),
        item("轻云出月", 0.836, 0.604),
        # left-side grid noise that must be ignored
        item("全部", 0.05, 0.05), item("+25", 0.1, 0.2), item("+25", 0.2, 0.2),
    ]


EXPECTED = {
    "echo": "Spearback",
    "type": 3,
    "rank": 5,
    "stat": "Havoc",
    "echoSet": "MoonlitClouds",
    "echoSubStatsType1": "CritRate", "echoSubStatsValue1": 9.3,
    "echoSubStatsType2": "HP", "echoSubStatsValue2": 8.6,
    "echoSubStatsType3": "ResonanceLiberationDMGBonus", "echoSubStatsValue3": 11.6,
    "echoSubStatsType4": "CritDMG", "echoSubStatsValue4": 13.8,
    "echoSubStatsType5": "BasicAttackDMGBonus", "echoSubStatsValue5": 7.1,
}


class TestMappings(unittest.TestCase):
    def test_echo_lookup(self):
        info = mappings.lookup_echo("箭簇熊")
        self.assertIsNotNone(info)
        self.assertEqual(info["key"], "Spearback")
        self.assertEqual(info["cost"], 3)

    def test_set_lookup(self):
        self.assertEqual(mappings.lookup_set("轻云出月"), "MoonlitClouds")
        self.assertEqual(mappings.lookup_set("凝夜白霜"), "FreezingFrost")

    def test_phantom_prefix_strips_to_base(self):
        # 异相 (Phantom) is cosmetic -> same key as the (Nightmare) base echo
        self.assertEqual(mappings.lookup_echo("異相·琉璃刀伶")["key"], "VitreumDancer")
        # garbled 梦魇->梦魔意 + separator vari/ + Phantom prefix
        self.assertEqual(
            mappings.lookup_echo("異相・梦魔意·无冠者")["key"], "NightmareCrownless"
        )
        # Nightmare base must NOT collapse to plain Crownless
        self.assertEqual(mappings.lookup_echo("梦魇·无冠者")["key"], "NightmareCrownless")
        self.assertEqual(mappings.lookup_echo("无冠者")["key"], "Crownless")

    def test_reminiscence_manual_mapping(self):
        info = mappings.lookup_echo("共鸣回响达妮娅")
        self.assertEqual(info["key"], "ReminiscenceDenia")
        self.assertEqual(info["cost"], 4)

    def test_manual_wiki_filled_echoes(self):
        self.assertEqual(mappings.lookup_echo("残星·重锤造匠")["key"], "FractsidusThruster")
        self.assertEqual(mappings.lookup_echo("嚣风戏猿")["key"], "Hoochief")
        self.assertEqual(mappings.lookup_echo("抛石幼猿")["key"], "Hooscamp")

    def test_ocr_junk_is_stripped(self):
        # OCR appends UI-icon emoji / @ / progress markers / colon separators;
        # names and sets must still resolve after cleaning to CJK-only.
        self.assertEqual(
            mappings.lookup_echo("共鸣回响·鸣式·虚造神型🌌")["key"],
            "ReminiscenceThrenodianVoidborneConstruct",
        )
        self.assertEqual(
            mappings.lookup_echo("共鸣回响·鸣式·利维亚坦")["key"],
            "ReminiscenceThrenodianLeviathan",
        )
        self.assertEqual(mappings.lookup_echo("格洛犸图")["key"], "Glommoth")
        self.assertEqual(mappings.lookup_echo("異相：辛吉勒姆")["key"], "Sigillum")  # colon sep
        self.assertEqual(mappings.lookup_echo("異相目・无妄者")["key"], "Dreamless")  # 目 garble
        self.assertEqual(
            mappings.lookup_set("碎梦亡鬼之魇🎯（1/1)"), "ShadowofShatteredDreams"
        )
        self.assertEqual(mappings.lookup_set("碎梦亡鬼之魔"), "ShadowofShatteredDreams")
        self.assertEqual(mappings.lookup_echo("角")["key"], "Jué")  # accented key
        self.assertEqual(mappings.lookup_echo("異相・异构武装")["key"], "SentryConstruct")
        self.assertEqual(mappings.lookup_echo("阿磁磁")["key"], "ZigZag")  # 嗞->磁 OCR

    def test_substat_value_sign_stripped(self):
        # OCR sometimes prefixes a substat value with a stray sign ('-7.9%').
        from src.echo_export.parser import parse_value, _is_number
        self.assertTrue(_is_number("-7.9%"))
        self.assertEqual(parse_value("-7.9%"), 7.9)
        self.assertEqual(parse_value("+30"), 30.0)

    def test_stat_percent_vs_flat(self):
        self.assertEqual(mappings.map_stat("攻击", "9.3%"), "ATK")
        self.assertEqual(mappings.map_stat("攻击", "100"), "ATK_FLAT")
        self.assertEqual(mappings.map_stat("暴击伤害", "13.8%"), "CritDMG")
        self.assertEqual(mappings.map_stat("暴击", "9.3%"), "CritRate")  # not CritDMG
        self.assertEqual(mappings.map_stat("湮灭伤害加成", "30.0%"), "Havoc")


class TestParser(unittest.TestCase):
    def test_is_equipment_page(self):
        self.assertTrue(is_equipment_page(spearback_items()))

    def test_not_equipment_page(self):
        # no 简述 anchor -> not the equipment page
        items = [it for it in spearback_items() if it.clean != "简述"]
        self.assertFalse(is_equipment_page(items))
        self.assertIsNone(parse_equipment_frame(items))

    def test_parse_full_record(self):
        rec = parse_equipment_frame(spearback_items())
        self.assertIsNotNone(rec)
        self.assertEqual(rec.to_optimizer_dict(), EXPECTED)
        self.assertEqual(rec.warnings, [])

    def test_skips_non_max_level(self):
        items = [it for it in spearback_items() if it.clean != "+25"]
        items.append(item("+20", 0.943, 0.141))
        self.assertIsNone(parse_equipment_frame(items))

    def test_skips_partially_loaded_panel(self):
        # missing the bottom anchors (声骸技能 / 合鸣效果) => captured mid-load => skip
        no_skill = [it for it in spearback_items() if it.clean != "声骸技能"]
        self.assertIsNone(parse_equipment_frame(no_skill))
        no_sonata = [it for it in spearback_items() if it.clean != "合鸣效果"]
        self.assertIsNone(parse_equipment_frame(no_sonata))

    def test_recognized_record_has_no_warnings(self):
        rec = parse_equipment_frame(spearback_items())
        self.assertTrue(rec.is_recognized)
        self.assertEqual(rec.warnings, [])

    def test_unmapped_set_flagged_but_still_parsed(self):
        # replace the sonata name with an unknown one -> warning + not recognized,
        # but the rest of the record (echo/stat/substats) still parses.
        items = [it for it in spearback_items() if it.clean != "轻云出月"]
        items.append(item("某未知合鸣", 0.836, 0.604))
        rec = parse_equipment_frame(items)
        self.assertIsNotNone(rec)
        self.assertFalse(rec.is_recognized)
        self.assertIsNone(rec.echo_set)
        self.assertEqual(rec.set_zh, "某未知合鸣")
        self.assertTrue(any("set not mapped" in w for w in rec.warnings))
        self.assertEqual(rec.echo, "Spearback")  # echo still recognized


class TestRecorder(unittest.TestCase):
    def test_dedup(self):
        rec1 = parse_equipment_frame(spearback_items())
        rec2 = parse_equipment_frame(spearback_items())
        r = EchoRecorder()
        self.assertTrue(r.add(rec1))
        self.assertFalse(r.add(rec2))  # identical content -> deduped
        self.assertEqual(len(r), 1)

    def test_atomic_save_roundtrip(self):
        import json
        import tempfile
        rec = parse_equipment_frame(spearback_items())
        r = EchoRecorder()
        r.add(rec)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "echoes.json")
            r.save(path)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        self.assertEqual(data, [EXPECTED])


def _onnxocr():
    try:
        import cv2  # noqa: F401
        from onnxocr.onnx_paddleocr import ONNXPaddleOcr  # noqa: F401
        return True
    except Exception:
        return False


@unittest.skipUnless(_onnxocr(), "onnxocr/opencv not installed")
class TestRealScreenshot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import cv2
        from onnxocr.onnx_paddleocr import ONNXPaddleOcr
        cls.cv2 = cv2
        # onnxocr's onnxruntime import is only used by the non-openvino backend,
        # and onnxruntime is NOT a declared dependency. The repo ships openvino
        # (requirements.txt), so prefer that backend; fall back to onnxruntime.
        cls.ocr = None
        for kwargs in ({"use_openvino": True, "use_npu": False},
                       {"use_openvino": False, "use_npu": False}):
            try:
                cls.ocr = ONNXPaddleOcr(use_angle_cls=False, **kwargs)
                break
            except Exception:
                continue
        if cls.ocr is None:
            raise unittest.SkipTest(
                "no onnxocr OCR backend available (install 'openvino' or 'onnxruntime')"
            )

    def _items(self, fname):
        img = self.cv2.imread(os.path.join(IMAGES, fname))
        h, w = img.shape[:2]
        result = self.ocr.ocr(img)[0]
        return from_onnxocr([result], w, h)

    def test_equipment_page_parses(self):
        rec = parse_equipment_frame(self._items("echo_enhance2.png"))
        self.assertIsNotNone(rec)
        d = rec.to_optimizer_dict()
        self.assertEqual(d["echo"], "Spearback")
        self.assertEqual(d["type"], 3)
        self.assertEqual(d["stat"], "Havoc")
        self.assertEqual(d["echoSet"], "MoonlitClouds")
        subs = {d[f"echoSubStatsType{i}"] for i in range(1, 6)}
        self.assertEqual(
            subs,
            {"CritRate", "HP", "ResonanceLiberationDMGBonus", "CritDMG", "BasicAttackDMGBonus"},
        )

    def test_enhancement_page_is_not_equipment(self):
        # find_add_mat.png is the 声骸强化 page (no 简述) -> not parsed
        self.assertIsNone(parse_equipment_frame(self._items("find_add_mat.png")))

    # Real captured equipment pages: (echo, type, stat, echoSet, {substat types}).
    # echo_1 = Reminiscence, echo_2 = Phantom·Nightmare variant, echo_4 = Phantom.
    REAL_ECHOES = {
        "echo_1.png": ("ReminiscenceDenia", 4, "CritDMG", "ChromaticFoam",
                       {"CritRate", "CritDMG", "BasicAttackDMGBonus", "HP", "DEF_FLAT"}),
        "echo_2.png": ("NightmareCrownless", 4, "CritRate", "SunSinkingEclipse",
                       {"BasicAttackDMGBonus", "ATK", "HeavyAttackDMGBonus", "EnergyRegen", "CritRate"}),
        "echo_3.png": ("DiurnusKnight", 3, "Spectro", "EternalRadiance",
                       {"HeavyAttackDMGBonus", "BasicAttackDMGBonus", "CritDMG", "EnergyRegen", "CritRate"}),
        "echo_4.png": ("VitreumDancer", 3, "Spectro", "EternalRadiance",
                       {"CritDMG", "ResonanceSkillDMGBonus", "EnergyRegen", "HP", "ATK_FLAT"}),
        "echo_5.png": ("Gulpuff", 1, "ATK", "CelestialLight",
                       {"ATK", "ResonanceLiberationDMGBonus", "CritDMG", "ATK_FLAT", "EnergyRegen"}),
        # 2552x1407 (~16:9) capture; name+level merge into one OCR box here, which
        # exercises the level-stripping in the name parser.
        "resolution.png": ("NightmareInfernoRider", 4, "CritRate", "MoltenRift",
                           {"CritDMG", "DEF_FLAT", "HeavyAttackDMGBonus", "ATK_FLAT", "ATK"}),
    }

    def test_real_max_level_echoes(self):
        for fname, (echo, typ, stat, eset, subtypes) in self.REAL_ECHOES.items():
            with self.subTest(image=fname):
                rec = parse_equipment_frame(self._items(fname))
                self.assertIsNotNone(rec, f"{fname} did not parse")
                d = rec.to_optimizer_dict()
                self.assertEqual(d["echo"], echo, fname)
                self.assertEqual(d["type"], typ, fname)
                self.assertEqual(d["stat"], stat, fname)
                self.assertEqual(d["echoSet"], eset, fname)
                got = {d[f"echoSubStatsType{i}"] for i in range(1, 6)}
                self.assertEqual(got, subtypes, fname)
                self.assertEqual(rec.warnings, [], f"{fname} warnings: {rec.warnings}")

    def test_non_max_level_echoes_skipped(self):
        # echo_6 (+10) and echo_7 (+0) are equipment pages but not max level
        for fname in ("echo_6.png", "echo_7.png"):
            with self.subTest(image=fname):
                self.assertIsNone(parse_equipment_frame(self._items(fname)))


if __name__ == "__main__":
    unittest.main()
