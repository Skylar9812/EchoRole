"""Static scenario translations and trusted room-language AI instruction."""
import json
from pathlib import Path
from functools import lru_cache
LANGUAGES = {'en':'English', 'zh-CN':'Simplified Chinese', 'zh-TW':'Traditional Chinese'}

@lru_cache
def scenario_translations(language):
    if language == 'en': return {}
    if language not in LANGUAGES: raise ValueError('Unsupported language')
    return json.loads((Path(__file__).parent / 'locales' / f'scenarios.{language}.json').read_text(encoding='utf-8'))

def localize_scenario(scenario, language):
    return {**scenario, **scenario_translations(language).get(scenario['id'], {})}

def language_instruction(session):
    language = (session or {}).get('language')
    if language not in LANGUAGES: return ''
    return f"Room response language: {LANGUAGES[language]}. Write all user-facing generated content, guidance, role briefs and situation text in this language, regardless of the user's input language. Preserve JSON field names. Do not translate or rewrite quoted user input. This overrides other language preferences."


# The scene-quality heuristic needs lexical markers in the output language.
# These are quality hints, not translations of participant-authored content.
STORY_MARKERS = {
    "zh-CN": {
        "scene": ("随后", "稍后", "当天", "当晚", "今晚", "明天", "次日", "第二天", "下周", "下个月", "周末", "早晨", "早上", "上午", "下午", "晚上", "午餐", "晚餐", "晚饭", "餐桌", "会议", "会后", "办公室", "截止", "发布", "生日", "纪念日", "旅行", "出游", "聚会", "咖啡", "电话", "消息", "短信", "计划", "提醒", "回家", "客厅"),
        "tension": ("但", "然而", "却", "虽然", "尽管", "仍", "担心", "担忧", "犹豫", "不确定", "误解", "压力", "边界", "界限", "不满", "受伤", "信任", "真诚", "以为", "认为", "期待", "分歧", "质疑", "沉默", "拒绝"),
        "abstract": ("双方都已采取行动", "双方现在都已行动", "冲突正在进入新的阶段", "互动向前推进", "紧张关系变得更加明显"),
    },
    "zh-TW": {
        "scene": ("隨後", "稍後", "當天", "當晚", "今晚", "明天", "次日", "第二天", "下週", "下周", "下個月", "週末", "周末", "早晨", "早上", "上午", "下午", "晚上", "午餐", "晚餐", "晚飯", "餐桌", "會議", "會後", "辦公室", "截止", "發布", "發佈", "生日", "紀念日", "旅行", "出遊", "聚會", "咖啡", "電話", "訊息", "消息", "簡訊", "計畫", "計劃", "提醒", "回家", "客廳"),
        "tension": ("但", "然而", "卻", "雖然", "儘管", "仍", "擔心", "擔憂", "猶豫", "不確定", "誤解", "壓力", "邊界", "界限", "不滿", "受傷", "信任", "真誠", "以為", "認為", "期待", "分歧", "質疑", "沉默", "拒絕"),
        "abstract": ("雙方都已採取行動", "雙方現在都已行動", "衝突正在進入新的階段", "互動向前推進", "緊張關係變得更加明顯"),
    },
}
