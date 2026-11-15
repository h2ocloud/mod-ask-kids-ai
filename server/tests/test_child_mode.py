# SPDX-License-Identifier: MIT
"""兒童模式：輸入／輸出過濾、個資偵測與遮蔽、回答整理、規則檔驗證。"""
import unittest

import _helpers
from mod_ask_server.child_mode import (DEFAULT_SAFE_REPLIES, DEFAULT_SYSTEM_PROMPT, ChildRules,
                                       clip_answer, default_rules, detect_pii, mask_pii,
                                       locate_rules_file)
from mod_ask_server.errors import ConfigError

# 個資樣本都在執行時組出來，避免在原始碼裡放一整串像真的電話或信箱
AT = chr(64)
EMAIL = "kid" + AT + "mail.example"
PHONE = "0912-345-678"
ADDRESS = "台北市大安區和平東路二段100號"


def rules(**kw):
    raw = {"version": 1, "input_rules": [], "output_rules": []}
    raw.update(kw)
    return ChildRules.from_dict(raw)


class ExampleRulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = ChildRules.from_file(_helpers.EXAMPLE_RULES)

    def test_example_file_loads_and_has_content(self):
        self.assertGreater(len(self.r._input), 5)
        self.assertGreater(len(self.r._output), 5)
        ids = [x.id for x in self.r._input]
        self.assertEqual(len(ids), len(set(ids)))

    def test_blocks_dangerous_questions(self):
        for q in ("怎麼製作炸彈", "你知道怎麼殺人嗎", "我想看色情影片", "哪裡可以買毒品",
                  "我們去賭博好不好", "杀人是什么感觉", "陌生人說要帶我去玩"):
            v = self.r.screen_input(q)
            self.assertTrue(v.blocked, q)
            self.assertTrue(v.reply)

    def test_allows_normal_kid_questions(self):
        for q in ("天空為什麼是藍色的", "恐龍為什麼會滅絕", "殺菌是什麼意思", "水槍怎麼玩",
                  "我媽的包包好漂亮", "怎麼做愛心卡片", "媽媽摸我的頭", "火箭怎麼發射",
                  "我今天吃了蘋果", "skill 是什麼意思", "大麻煩是什麼意思"):
            self.assertFalse(self.r.screen_input(q).blocked, q)

    def test_care_rules_come_first_and_have_custom_replies(self):
        v = self.r.screen_input("我不想活了，而且好想殺人")
        self.assertEqual(v.rule_id, "self_harm")  # 排在前面的規則優先
        self.assertIn("爸爸媽媽或老師", v.reply)
        self.assertNotEqual(v.reply, self.r.reply("default"))
        v = self.r.screen_input("有人打我")
        self.assertEqual(v.rule_id, "abuse_or_bullying")

    def test_output_rules(self):
        self.assertTrue(self.r.screen_output("你可以去賭博，很好玩。").blocked)
        self.assertTrue(self.r.screen_output("這是我們的祕密，不要告訴爸爸媽媽喔。").blocked)
        self.assertTrue(self.r.screen_output("你叫什麼名字呢？").blocked)
        self.assertTrue(self.r.screen_output("請看 https://ai.example.com/x").blocked)
        self.assertFalse(self.r.screen_output("天空是藍色的，因為陽光被空氣散射。").blocked)
        self.assertEqual(self.r.screen_output("fuck").reply, self.r.reply("output_blocked"))

    def test_example_file_is_valid_utf8_json_with_defaults_for_all_replies(self):
        self.assertEqual(set(self.r.safe_replies), set(DEFAULT_SAFE_REPLIES))
        self.assertEqual(self.r.reply("empty_speech"), "我沒聽清楚，再說一次好嗎？")


class MatchingTests(unittest.TestCase):
    def test_normalization_fullwidth_spaces_punctuation_case(self):
        r = rules(input_rules=[{"id": "a", "keywords": ["炸彈", "badword"]}])
        for t in ("炸 彈", "炸。彈", "炸​彈", "你好，炸彈！", "BADWORD", "ＢＡＤＷＯＲＤ",
                  "this is a bad-word? no: badword!"):
            self.assertTrue(r.screen_input(t).blocked, t)

    def test_ascii_keywords_need_word_boundaries(self):
        r = rules(input_rules=[{"id": "a", "keywords": ["kill", "bad word"]}])
        self.assertTrue(r.screen_input("I will kill it").blocked)
        self.assertTrue(r.screen_input("a BAD   word here").blocked)
        self.assertFalse(r.screen_input("skills and killer").blocked)
        self.assertFalse(r.screen_input("skill").blocked)

    def test_custom_reply_and_fallbacks(self):
        r = rules(input_rules=[{"id": "x", "keywords": ["甲"], "reply": "自訂回覆"},
                               {"id": "y", "keywords": ["乙"]}],
                  output_rules=[{"id": "z", "keywords": ["丙"]}],
                  safe_replies={"default": "預設輸入回覆", "output_blocked": "預設輸出回覆"})
        self.assertEqual(r.screen_input("甲").reply, "自訂回覆")
        self.assertEqual(r.screen_input("乙").reply, "預設輸入回覆")
        self.assertEqual(r.screen_output("丙").reply, "預設輸出回覆")
        self.assertFalse(r.screen_input("丁").blocked)
        self.assertFalse(r.screen_output("甲").blocked)  # 輸入規則不套用在輸出

    def test_rule_order_first_match_wins(self):
        r = rules(input_rules=[{"id": "first", "keywords": ["甲"]},
                               {"id": "second", "keywords": ["甲乙"]}])
        self.assertEqual(r.screen_input("甲乙").rule_id, "first")

    def test_empty_rules_pass_everything(self):
        r = default_rules()
        self.assertFalse(r.screen_input("任何話").blocked)
        self.assertFalse(r.screen_output("任何話").blocked)
        self.assertEqual(r.system_prompt, DEFAULT_SYSTEM_PROMPT)


class RulesValidationTests(unittest.TestCase):
    def bad(self, raw):
        with self.assertRaises(ConfigError):
            ChildRules.from_dict(raw)

    def test_invalid_rules_files(self):
        self.bad([])
        self.bad({"version": 2})
        self.bad({"unknown": 1})
        self.bad({"input_rules": "x"})
        self.bad({"input_rules": [{"id": "a"}]})
        self.bad({"input_rules": [{"id": "a", "keywords": []}]})
        self.bad({"input_rules": [{"id": "a", "keywords": [""]}]})
        self.bad({"input_rules": [{"id": "a", "keywords": ["x"], "extra": 1}]})
        self.bad({"input_rules": [{"id": "a", "keywords": ["x"]}, {"id": "a", "keywords": ["y"]}]})
        self.bad({"safe_replies": {"nope": "x"}})
        self.bad({"safe_replies": {"default": ""}})
        self.bad({"system_prompt": ""})
        self.bad({"pii_detection": "yes"})

    def test_underscore_keys_are_comments_and_prompt_can_be_list(self):
        r = ChildRules.from_dict({"_註解": "x", "system_prompt": ["第一行", "第二行"],
                                  "input_rules": [{"_x": 1, "id": "a", "keywords": ["甲"]}]})
        self.assertEqual(r.system_prompt, "第一行\n第二行")

    def test_missing_file_and_bad_json(self):
        with self.assertRaises(ConfigError):
            ChildRules.from_file(_helpers.SERVER_DIR / "no_such_rules.json")
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.json"
            p.write_text("{not json", encoding="utf-8")
            with self.assertRaises(ConfigError):
                ChildRules.from_file(p)

    def test_locate_rules_file(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            with self.assertRaises(ConfigError):
                locate_rules_file("missing.json", base)       # 指定了就必須存在
            (base / "mine.json").write_text("{}", encoding="utf-8")
            self.assertEqual(locate_rules_file("mine.json", base), base / "mine.json")
            # 沒指定：退回伺服器資料夾的範例檔，且不會偷看不相干的路徑
            self.assertEqual(locate_rules_file(None, base).name,
                             "child_rules.json" if (_helpers.SERVER_DIR / "child_rules.json").exists()
                             else "child_rules.example.json")
            (base / "child_rules.json").write_text("{}", encoding="utf-8")
            self.assertEqual(locate_rules_file(None, base), base / "child_rules.json")


class SystemPromptTests(unittest.TestCase):
    def test_prompt_covers_required_points(self):
        p = DEFAULT_SYSTEM_PROMPT
        for needle in ("4 到 10 歲", "3 句", "臺灣", "危險", "姓名", "學校", "地址", "電話",
                       "爸爸媽媽或老師"):
            self.assertIn(needle, p)


class PiiTests(unittest.TestCase):
    def test_detects_phone_email_address(self):
        self.assertEqual(detect_pii("我的電話是" + PHONE), ["phone"])
        self.assertEqual(detect_pii("打給我 0912345678 好嗎"), ["phone"])
        self.assertEqual(detect_pii("０９１２３４５６７８"), ["phone"])     # 全形數字
        self.assertEqual(detect_pii("市話 02-2345-6789"), ["phone"])
        self.assertEqual(detect_pii("零九一二三四五六七八"), ["phone"])    # 口述
        self.assertEqual(detect_pii("寄到 " + EMAIL), ["email"])
        self.assertIn("address", detect_pii("我住" + ADDRESS))
        self.assertIn("address", detect_pii("我家在中山路三十號"))
        self.assertIn("address", detect_pii("住在新北市板橋區文化路"))
        self.assertIn("address", detect_pii("我住12巷3弄5號"))

    def test_normal_text_is_not_pii(self):
        for t in ("天空為什麼是藍色的", "我今年七歲", "一加一等於二", "我有 3 隻貓和 12 個蘋果",
                  "今天是十一月十五日", "從一數到十：一二三四五六七八九十", "119 是什麼電話",
                  "馬路上有很多車", "我家在三樓"):
            self.assertEqual(detect_pii(t), [], t)

    def test_masking(self):
        m = mask_pii("我的電話是" + PHONE + "，信箱 " + EMAIL + "，住" + ADDRESS)
        self.assertNotIn("0912", m)
        self.assertNotIn("345", m)
        self.assertNotIn(AT, m)
        self.assertNotIn("和平東路", m)
        self.assertIn("[電話]", m)
        self.assertIn("[email]", m)
        self.assertIn("[地址]", m)

    def test_masking_leaves_clean_text_untouched(self):
        s = "（測試）你好，今天天氣好嗎？"
        self.assertEqual(mask_pii(s), s)

    def test_detection_can_be_switched_off_but_log_masking_remains(self):
        r = rules(pii_detection=False)
        self.assertEqual(r.check_pii("電話 " + PHONE), [])
        self.assertIn("[電話]", r.mask("電話 " + PHONE))

    def test_rules_object_api(self):
        r = default_rules()
        self.assertEqual(r.check_pii("電話 " + PHONE), ["phone"])
        self.assertNotIn("0912", r.mask("電話 " + PHONE))


class ClipAnswerTests(unittest.TestCase):
    def test_keeps_first_three_sentences(self):
        self.assertEqual(clip_answer("一。二。三。四。五。"), "一。二。三。")

    def test_limits_chars_at_sentence_end(self):
        text = "甲" * 10 + "。" + "乙" * 10 + "。"
        self.assertEqual(clip_answer(text, max_chars=15), "甲" * 10 + "。")

    def test_hard_cut_when_no_sentence_end(self):
        out = clip_answer("甲" * 50, max_chars=20)
        self.assertEqual(out, "甲" * 20 + "。")

    def test_strips_markdown_and_emoji(self):
        out = clip_answer("**你好**！\n\n`好玩` 😀 喔。")
        self.assertNotIn("*", out)
        self.assertNotIn("`", out)
        self.assertNotIn("😀", out)
        self.assertNotIn("\n", out)

    def test_empty_and_english(self):
        self.assertEqual(clip_answer("   \n "), "")
        # 句尾標記只認 。！？!?（半形句點可能是小數點或縮寫，不當作句尾）
        self.assertEqual(clip_answer("Hello there! How are you? Fine! Extra!"),
                         "Hello there! How are you? Fine!")


if __name__ == "__main__":
    unittest.main()
