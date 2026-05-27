from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .characters import CHARACTER_ALIASES, GROUP_CHARACTER_NAMES
from .io import read_json, read_text


@dataclass(frozen=True)
class PlatformProfile:
    id: str
    label: str
    prompt_label: str
    negative_label: str
    description: str
    usage_hint: str
    prefers_compact: bool = False
    supports_negative_prompt: bool = True


@dataclass(frozen=True)
class ContextSnippet:
    source: str
    line: int
    text: str
    score: int


DEFAULT_COLOR_PALETTE = (
    "目标是二次元人物现实化，不是通用现实主义人像；世界要像游乐园和五光十色的舞台，现实空间用于衬托角色的独特颜色、天赋、韵味和风采；"
    "色彩随主题和现场光线变化，但先用正向色彩锁定：干净有活力的偏暖肤色、清楚角色发色、可爱服装层次、环境色块和正常偏明亮曝光；"
    "日常、旅行、校园、练习室、温室、小院和咖啡场景使用自然到适度鲜活的饱和度；"
    "可以有类似 TikTok/小红书打卡照的清透修图、轻微梦幻感和可爱氛围；"
    "创作态度是喜爱和欣赏，千方百计展示人物美丽；克制、安静或失落只描述表情和关系，不等于平淡纪实、全局冷灰、素色、疲惫憔悴、雾面低饱和或低曝光；"
    "最终画面要有用户愿意保存的照片魅力，而不是只完成角色设定。"
)

GROUP_FACE_GUIDE = GROUP_CHARACTER_NAMES

CHARACTER_FACE_GUIDE = {
    "高松灯": "高松灯：灰紫色短层次 bob，发色正向锁定：muted gray-violet short layered bob，环境光下可有紫灰或灰蓝反光，不是纯黑、银灰白或高饱和亮紫；灰紫偏蓝灰眼眸（gray-violet eyes），清澈内敛；脸型极短圆软，下巴极短圆软，柔软脸颊、鼻唇存在感自然；小嘴常抿起，嘴角不上翘；眉眼清澈内收，视线常向下或内收；肩膀习惯性内收；不要长脸、尖下巴、普通黑短发、大学生感、成熟骨相、职业女性气质、成熟凌厉或锐利脸。",
    "千早爱音": "千早爱音：樱粉色长发，发色正向锁定：soft sakura-pink long hair，真实发丝质感，有空气感刘海或松散侧编，粉棕只作阴影和低饱和转译，不能退成普通棕发、浅茶发或蜂蜜棕；圆润短脸，下巴短但稍有轮廓（不是尖下巴也不是完全无下巴的圆脸）；柔软饱满的苹果肌；小鼻小嘴，嘴角天然上翘；眉毛上扬外展，眉眼间距舒展，眼型偏圆偏大，明亮灰蓝眼眸（bright gray-blue eyes），清澈通透，视线主动向外看；不要退成普通棕发、浅茶发、成熟模板脸或只会营业甜笑的网红脸；不要长脸、尖下巴、高颧骨、菱形脸、欧美化面孔、成熟骨相、向下视线或内收表情、看起来20岁以上。",
    "要乐奈": "要乐奈：发色正向锁定：silver-white or cold-white short bob，真实发丝和冷光层次，避免假发感或贵族精致感；银白短 bob，小圆脸、短下巴、柔软脸颊、小鼻小嘴；上眼皮微微下垂呈半阖状态，即使睁眼也像随时要闭上；眼神清澈偏圆；异色瞳：一暖一冷的微妙差异（one eye warm amber-gold, one eye cool blue-gray），必须可见不消失；窄肩低姿态；不要鹅蛋脸白发美女、欧美女性观感、高挑宽肩、男性化、中性帅哥、成熟疲惫女子或贵族白发。",
    "长崎素世": "长崎素世：蜂蜜棕顺滑长发，温暖但不是金发，不能漂成浅金、亮金、普通深棕或爱音式粉棕；蓝色眼眸（blue eyes），杏仁形眼，眼尾微微上扬，清澈但略带克制；脸部修长偏窄，下巴有柔和轮廓但不尖，颧骨轻微可见但不突出；眉眼温柔克制；不要金发化、爱音式活泼大笑、圆脸化、礼仪模板脸或只剩漂亮长发女生。",
    "椎名立希": "椎名立希：深黑褐长直发，发色正向锁定：very dark brownish-black long straight hair，真实发丝质感和冷光，不要纯黑或暖棕；深灰棕眼眸（dark gray-brown eyes），锐利紧绷；下巴窄而收束，脸颊薄平，鼻梁挺但不高；眉毛粗而平直，嘴唇薄而常抿紧；脸部线条利落，眉眼锐利紧绷，下颌收束；不要短发化、男性化、粗鲁化、圆软脸或丰满唇。",
    "若叶睦": "若叶睦：柔和浅绿顺滑及腰长发，现实化时只加入灰调冷绿反光；下巴极短微尖，娃娃脸，稚气柔软脸、小鼻小嘴；金棕眼（golden-brown eyes），清澈偏大，有玻璃珠般安静反光；不要普通清冷美女、素世式温柔模板脸、鲜绿假发、恐怖人偶或成熟性感化。",
    "丰川祥子": "丰川祥子：冷金、银白金或端庄浅发，发色正向锁定：cool ash-blonde or silver-gold，真实发丝和冷光层次，不要暖金或亮金；冷灰蓝浅色眼眸（cool gray-blue eyes），眼型细长偏冷，常半垂视线；脸部精致偏窄，下巴略尖但不锐利，颧骨轻微可见，五官紧凑精致；嘴唇薄而紧抿，嘴角不上翘；不要反派脸、恶役大小姐脸、圆脸、丰满唇、暖色调面孔或随性白发。",
    "三角初华": "三角初华：自然暖棕或深棕柔顺长发，发色正向锁定：warm medium-brown or dark-brown silky long hair，真实发丝质感，暖棕不是深黑也不是浅金；温暖深棕眼眸（warm brown eyes），眼型偏大偏暖，眼尾自然下垂呈温柔弧度；脸部成熟端庄，鹅蛋脸偏长但不尖，下巴柔和收窄，五官舒展大气；嘴唇饱满，嘴角自然微翘；不要过度华丽舞台脸、浓妆成熟感、成人性感化、冷色调面孔或尖锐骨相。",
}

CHARACTER_FACE_GUIDE_SHORT = {
    "高松灯": "高松灯：muted gray-violet short layered bob，灰紫偏蓝灰眼眸；灰紫色短发色相清楚，不是纯黑或银灰白；极短圆软脸、柔软脸颊、极短圆下巴，小嘴常抿起嘴角不上翘；面部气质内向安静、清澈略怯但真诚，视线常内收或向下，肩膀微收。不要长脸、尖下巴、冷酷短发美女或锐利脸。",
    "千早爱音": "千早爱音：soft sakura-pink long hair，明亮灰蓝眼眸，嘴角天然上翘；真实樱粉发丝，粉棕只作阴影不退成棕发；圆润短脸、苹果肌饱满、小下巴、小鼻小嘴；眉毛上扬外展，眉眼外放，笑意主动像先一步靠近别人，有想被看见又怕被看穿的微微用力。不要棕发化、浅茶化、成熟网红脸、长脸、尖下巴、高颧骨、欧美化面孔或看起来20岁以上。",
    "要乐奈": "要乐奈：先锁娇小可爱的东亚少女，再锁银白短 bob；silver-white short bob，真实发丝冷光层次；小圆脸、短下巴、柔软脸颊、小鼻小嘴，半阖睡眼上眼皮微微下垂；面部气质猫感游离，眼神像观察声音不观察人；异色瞳一暖一冷微妙可见；窄肩低姿态，像自然闯入画面。不要鹅蛋脸白发美女、欧美成熟女性、高挑宽肩、中性帅哥。",
    "长崎素世": "长崎素世：蜂蜜棕顺滑长发，蓝色杏仁形眼、眼尾微扬；修长偏窄脸，下巴有柔和轮廓但不尖，颧骨轻微可见；端正温柔，礼貌笑容里有维持场面的压力；贝斯/整理动作只是辅助。不要粉棕化、浅金/亮金发、圆脸化。",
    "椎名立希": "椎名立希：very dark brownish-black 长直发，深灰棕锐利眼眸；窄下巴、平眉、薄唇常抿，脸颊薄平；脸部线条利落，眉眼锐利紧绷，站姿警觉可靠；鼓槌/鼓组只是辅助。不要短发化、男性化、粗鲁化或圆软脸。",
    "若叶睦": "若叶睦：柔和浅绿顺滑及腰长发，极短微尖下巴、最娃娃脸，稚气柔软脸、小鼻小嘴；金棕眼（golden-brown eyes）清澈偏大有玻璃珠反光，慢半拍发呆感、低垂视线、植物性安静。不要清冷美女、素世式温柔模板脸、鲜绿假发、恐怖人偶或成熟性感化。",
    "丰川祥子": "丰川祥子：cool ash-blonde or silver-gold 真实冷光发丝，冷灰蓝浅色眼眸；眼型细长偏冷，常半垂视线；脸部精致偏窄，下巴略尖但不锐利，五官紧凑精致；唇薄紧抿嘴角不上翘，精致克制、被秩序压住情绪。不要反派脸、恶役大小姐脸、暖金发、圆脸或随性白发。",
    "三角初华": "三角初华：warm medium-brown 柔顺长发，温暖深棕眼眸；眼型偏大偏暖，眼尾自然下垂呈温柔弧度；鹅蛋脸偏长但不尖，下巴柔和收窄，五官舒展大气；唇饱满嘴角自然微翘，温柔从容像幕后引路人。不要华丽浓妆舞台脸、冷色调面孔或尖锐骨相。",
}

CHARACTER_CUTE_ANCHOR = {
    "高松灯": (
        "第一眼像灯本人：圆软内收的短脸、清澈略怯但真诚的眼神，"
        "可爱来自微小动作里的倔强——低头写字时抿嘴、握麦克风前深吸气、被拍到时微微缩肩但没有躲开；"
        "保存级社交照片质感，清透漂亮但不是网红甜笑，是认真害羞的漂亮。"
    ),
    "千早爱音": (
        "第一眼像爱音本人：樱粉色长发、明亮灰蓝眼眸，圆润短脸、苹果肌饱满、小下巴、小鼻小嘴、嘴角天然上翘的高中生面孔，"
        "眉毛上扬外展、眉眼间距舒展、视线主动向外看，笑意来得快——不是摆出来的笑而是嘴角本来就翘着所以随时像在笑；"
        "可爱来自主动社交里的轻快节奏——挥手、回头笑、举手机自拍时嘴角先一步翘起，"
        "有一分想被看见又怕被看穿的微微用力；保存级社交照片质感，清透漂亮、明亮亲和、非普通路人。"
    ),
    "要乐奈": (
        "第一眼像乐奈本人：小圆脸、短下巴、游离清澈的眼神，"
        "可爱来自安静里的猫感——像突然被声音或点心吸引而转头、低头拨弦时的专注、"
        "站在门口或角落的松弛低姿态；保存级社交照片质感，清透漂亮但不是冷酷白发美女，是娇小安静的可爱。"
    ),
    "长崎素世": (
        "第一眼像素世本人：蜂蜜棕顺滑长发、蓝色杏仁形眼眼尾微扬，修长偏窄的脸、下巴柔和轮廓、颧骨轻微可见，"
        "可爱来自礼貌微笑里维持场面的微微用力和偶尔流露的深层怀旧；"
        "保存级社交照片质感，漂亮端庄但不是模板礼仪脸。"
    ),
    "椎名立希": (
        "第一眼像立希本人：深黑褐长直发、深灰棕锐利眼眸，窄下巴、粗平眉毛、薄唇常抿紧的利落面孔，"
        "可爱来自外表冷硬下的保护欲——鼓槌转指的利落、看向灯时眼神不自觉柔和；"
        "保存级社交照片质感，帅气但不男性化，是有棱角的少女感。"
    ),
    "若叶睦": (
        "第一眼像睦本人：浅绿顺滑长发、稚气柔软脸、极短微尖下巴的最娃娃脸面孔，小鼻小嘴、金棕眼（golden-brown eyes）清澈偏大有玻璃珠反光，"
        "可爱来自慢半拍的发呆感和笨拙善意——递东西时犹豫、被叫到名字时慢一拍转头；"
        "保存级社交照片质感，精致安静但不是恐怖人偶、清冷美女或素世式温柔模板脸。"
    ),
    "丰川祥子": (
        "第一眼像祥子本人：冷金或银白金浅发、冷灰蓝细长眼眸，精致偏窄的脸、下巴略尖但不锐利、五官紧凑精致、唇薄紧抿嘴角不上翘，"
        "可爱来自被秩序压住的脆弱——低头时眼睫遮住情绪、指尖在琴键上犹豫的停顿；"
        "保存级社交照片质感，高雅但不是反派大小姐脸。"
    ),
    "三角初华": (
        "第一眼像初华本人：暖棕色柔顺长发、温暖深棕大眼，鹅蛋脸偏长、下巴柔和收窄、五官舒展大气、眼尾自然下垂、唇饱满嘴角微翘的温柔面容，"
        "可爱来自幕后引路人的温和包容——看向同伴时微微侧头、递出歌词纸时的安静鼓励；"
        "保存级社交照片质感，温柔漂亮但不是华丽舞台脸。"
    ),
}

PLATFORM_PROFILES = {
    "generic": PlatformProfile(
        id="generic",
        label="通用外站",
        prompt_label="推荐主 Prompt",
        negative_label="负面 Prompt",
        description="面向大多数外部图片生成平台的中文说明书格式。",
        usage_hint="复制主 Prompt，并把参考图作为附件上传；若平台支持负面词，再复制负面 Prompt。",
    ),
    "midjourney": PlatformProfile(
        id="midjourney",
        label="Midjourney",
        prompt_label="Midjourney 单段 Prompt",
        negative_label="避免项",
        description="偏单段、紧凑、摄影关键词明确的 Midjourney 输入格式。",
        usage_hint="复制单段 Prompt。避免项可按需改写为 `--no ...`，参考图仍需在外站界面单独上传。",
        prefers_compact=True,
        supports_negative_prompt=False,
    ),
    "stable-diffusion": PlatformProfile(
        id="stable-diffusion",
        label="Stable Diffusion / SDXL",
        prompt_label="Positive Prompt",
        negative_label="Negative Prompt",
        description="拆分正向与负向提示词，适合 SDXL、ComfyUI、WebUI 类流程。",
        usage_hint="正向 Prompt 放入 positive，负面 Prompt 放入 negative；参考图用于 IP-Adapter、ControlNet 或图生图节点。",
    ),
    "jimeng": PlatformProfile(
        id="jimeng",
        label="即梦/豆包类中文平台",
        prompt_label="中文主 Prompt",
        negative_label="不希望出现",
        description="偏自然语言、中文画面说明、强调主体动作和参考图用途的格式。",
        usage_hint="复制中文主 Prompt，并把参考图作为图片参考上传；负面项可放入平台的“不希望出现”区域。",
    ),
}


SCENE_INFERENCE_RULES = {
    "mood": [
        (("放学", "练习室", "天文", "歌词本", "乐队日常"), "温柔日常、安静创作、笨拙互相补位"),
        (("雨", "雨夜", "等人", "便利店"), "安静等待、克制孤独"),
        (("直播", "连麦", "弹幕"), "紧张但真诚、被陪伴"),
        (("舞台", "live", "演出"), "临场爆发、克制紧张"),
        (("黄昏", "夕阳"), "温柔、余韵、轻微亲密"),
        (("墓", "旧物", "回忆"), "怀念、修复、未说出口"),
    ],
    "shot": [
        (("五人", "团队", "群像", "同框"), "35mm 广角中景，五人同框但动作错落"),
        (("特写", "脸", "表情"), "50mm 或 85mm 中近景，主体脸部清楚"),
        (("全身", "站位", "立绘"), "全身中景，保留服装和身体姿态"),
        (("雨", "雨夜", "雨后", "便利店"), "50mm 中近景，保留街灯和湿地反光"),
        (("白天", "旅行", "街拍", "步行街", "约会", "古镇", "海边"), "35mm 旅行街拍中景，保留人物互动和真实环境"),
        (("直播", "练习室"), "35mm 中景，桌面和人物关系都清楚"),
    ],
    "lighting": [
        (("夜市", "灯笼", "霓虹"), "暖色街灯、摊位光和少量霓虹反光"),
        (("雨夜", "雨天", "雨后", "便利店"), "雨后天光、店铺白光、街灯和湿地反光"),
        (("直播", "屏幕", "电脑", "弹幕"), "屏幕冷光混合台灯暖光"),
        (("黄昏", "夕阳"), "黄金时刻侧逆光"),
        (("舞台", "live", "演出"), "冷暖交错舞台背光"),
        (("教室", "窗边"), "柔和窗光"),
        (("白天", "正午", "旅行", "街拍", "步行街"), "明亮自然日光"),
    ],
    "color_palette": [
        (("雨", "雨夜", "雨后", "便利店", "阴天"), "雨天可以偏冷，但必须保留街灯、便利店或窗光的暖色反差，肤色自然，湿地反光明亮，不要整张蓝灰。"),
        (("直播", "屏幕", "电脑", "弹幕", "练习室"), "屏幕冷光、台灯暖光和练习室环境光要平衡，桌面道具和角色发色有清楚色块，不做灰暗低曝光。"),
        (("舞台", "live", "演出", "灯海", "后台"), "舞台蓝白光、追光和局部暖色灯可以更明确，暗部保留细节，不把人物肤色压成灰。"),
        (("夜市", "灯笼", "霓虹"), "夜市和霓虹可以使用暖灯、摊位光和少量彩色反光，人物肤色保持自然，不要压成灰暗夜景。"),
        (("黄昏", "夕阳", "傍晚", "晚霞"), "暖金色高光和柔和肤色，阴影保持通透，角色发色和道具色保留清楚。"),
        (("温室", "植物园", "花", "小院", "公园"), "新鲜绿色、玻璃漫射光和少量暖日光为主，画面明亮通透，人物肤色柔和。"),
        (("教室", "窗边", "校园", "放学"), "干净午后窗光，背景轻柔但不灰，校服、发色和脸部肤色保持清楚。"),
        (("墓", "办公室", "车站", "冷白", "夜景"), "克制冷调可以保留，但曝光正常，肤色和角色发色不能被灰雾吞掉，画面需要局部暖光或明确色块。"),
        (("正午", "白天", "阳光", "旅行", "街拍", "步行街", "海边", "湖", "雪山", "古镇", "咖啡", "约会"), "明亮自然曝光，清透空气感，肤色和服装识别色清楚，饱和度自然偏鲜活，避免灰雾滤镜。"),
    ],
    "lens": [
        (("五人", "团队", "群像", "同框", "练习室"), "35mm"),
        (("特写", "脸", "表情", "等待"), "50mm"),
        (("舞台", "主唱"), "85mm"),
    ],
    "outfit": [
        (("校", "教室", "放学"), "现实化校服或校服外搭针织开衫"),
        (("雨", "雨夜", "雨后", "便利店"), "校服外搭宽松外套，衣料有轻微雨痕"),
        (("旅行", "街拍", "步行街", "约会"), "日常出行私服，保留角色识别色和轻便层次"),
        (("直播", "练习室"), "休闲排练服，带少量乐队识别色"),
        (("舞台", "live", "演出"), "现实化蓝白黑舞台服或排练外套"),
    ],
    "notes": [
        (("雨", "便利店", "等人"), "用透明伞、歌词本、湿地反光、门口白光表达等待；不要夸张哭喊。"),
        (("直播", "弹幕", "屏幕"), "屏幕文字不要可读，只表现为柔和短线、光点和反光。"),
        (("五人", "团队", "群像"), "每个人都要有不同动作和视线，避免整齐偶像合照。"),
    ],
}


ASPECT_RATIO_RULES = [
    (("手机壁纸", "竖图", "竖版", "全身", "海报"), "9:16"),
    (("头像", "图标", "方图", "正方形"), "1:1"),
    (("五人", "团队", "群像", "同框", "直播", "舞台"), "16:9"),
    (("双人", "旅行", "街拍", "日常"), "3:4"),
]


CONTEXT_ALIASES = {
    "直播": ["直播", "弹幕", "屏幕", "连麦", "B 站", "B站", "麦克风", "声卡", "电脑"],
    "雨": ["雨", "雨夜", "湿地", "街灯", "透明伞", "便利店", "等待"],
    "便利店": ["便利店", "夜晚街道", "街灯", "门口", "等待"],
    "歌词": ["歌词", "歌词纸", "歌词本", "笔记本", "麦克风"],
    "团队": ["多人", "五人", "群像", "同框", "乐队", "练习室"],
    "五人": ["多人", "五人", "群像", "同框", "乐队", "练习室"],
    "舞台": ["舞台", "Live House", "live", "演出", "麦克风", "灯海"],
    "练习室": ["练习室", "线缆", "谱架", "吉他包", "鼓槌", "乐器"],
    "天文": ["天文", "星图", "望远镜", "灰尘", "活动室"],
    "墓": ["墓", "墓园", "蓝花楹", "湿石板", "歉意"],
    "小院": ["小院", "归巢", "抹茶", "吉他包", "黄昏"],
    "旅行": ["旅行", "街拍", "江边", "古镇", "海边", "城市"],
}


CONTEXT_FILES = [
    "story_bible.md",
    "world/mygo_original_visual_bank.md",
    "references/mygo_realized_good_results.md",
    "references/mygo_visual_refs.md",
]


NEGATIVE_PROMPT_OMIT_TERMS = (
    "情侣写真感",
    "过度亲密肢体接触",
    "挑逗姿势",
    "泳装性化",
    "臀胸特写",
    "写真棚感",
    "商业偶像营业",
    "不要把红色吉他或吉他包省掉",
)


def platform_choices() -> list[str]:
    return sorted(PLATFORM_PROFILES)


def get_platform_profile(platform: str) -> PlatformProfile:
    normalized = (platform or "generic").strip()
    if normalized not in PLATFORM_PROFILES:
        raise ValueError(f"Unknown prompt doc platform: {platform}")
    return PLATFORM_PROFILES[normalized]


def extract_primary_scene_text(theme: str) -> str:
    text = re.split(r"[；;。]", theme, maxsplit=1)[0].strip()
    if "：" in text:
        text = text.split("：", 1)[-1].strip()
    return text or theme.strip()


def infer_scene_fields(theme: str) -> dict[str, str]:
    inferred: dict[str, str] = {}
    lower = theme.lower()
    for field, rules in SCENE_INFERENCE_RULES.items():
        best_value = ""
        best_score = 0
        for keywords, value in rules:
            score = sum(1 for keyword in keywords if keyword.lower() in lower)
            if score <= 0:
                continue
            if best_value == "" or score > best_score:
                best_value = value
                best_score = score
        if best_value:
            inferred[field] = best_value
    return inferred


def infer_aspect_ratio(theme: str, character: str = "") -> str:
    text = f"{theme}\n{character}"
    for keywords, value in ASPECT_RATIO_RULES:
        if has_any_keyword(text, keywords):
            return value
    return "3:4"


def has_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(keyword.lower() in lower for keyword in keywords)


def _resolve_scene_members(character: str, scene: str) -> list[str]:
    """Return the subset of group members mentioned in the scene text."""
    character_id = character.strip().lower()
    text = f"{character}\n{scene}"
    text_lower = text.lower()

    _SINGLE_CHAR_BOUNDARY_RE = re.compile(r"(?<![一-龥])([一-鿿])(?![一-龥])")

    for group_name, names in GROUP_FACE_GUIDE.items():
        if character_id != group_name.lower():
            continue
        found = []
        for name in names:
            if name in text:
                found.append(name)
            else:
                for alias, canonical in CHARACTER_ALIASES.items():
                    if canonical != name:
                        continue
                    if len(alias) >= 2 and alias.lower() in text_lower:
                        found.append(name)
                        break
                    if len(alias) == 1:
                        standalone = set(_SINGLE_CHAR_BOUNDARY_RE.findall(text))
                        if alias in standalone:
                            found.append(name)
                            break
        return found

    return []


def infer_group_face_lock(character: str, scene: str) -> str:
    text = f"{character}\n{scene}"
    character_id = character.strip().lower()

    scene_members = _resolve_scene_members(character, scene)
    n = len(scene_members) if scene_members else 0
    wants_five = has_any_keyword(text, ("全员", "五人", "五位", "团队", "群像", "同框", "成员"))
    wants_four = has_any_keyword(text, ("四人", "四位"))
    wants_three = has_any_keyword(text, ("三人", "三位"))
    wants_two = has_any_keyword(text, ("双人", "两人", "二人", "两位"))
    has_explicit_multi_character = bool(re.search(r"[+/、,，&和]", character))

    if n == 1:
        return ""
    if n == 2:
        return (
            "人数和脸部：先固定两位独立角色同框，不要裁成单人头像；"
            "两张脸都要可见且互不复制，用脸型、发型轮廓、表情习惯、站位和动作分工区分角色。"
        )
    if n == 3:
        return (
            "人数和脸部：先固定三位独立角色同框，不要裁成单人头像或只突出一张脸；"
            "三张脸都要可见且互不复制，用脸型、发型轮廓、表情习惯、站位和动作分工区分角色。"
        )
    if n == 4:
        return (
            "人数和脸部：先固定四位独立角色同框，不要裁成单人头像或只突出一张脸；"
            "四张脸都要可见且互不复制，边缘人物也要清楚。"
            "用脸型、眉眼气质、表情习惯、动作姿态、身高体态和互动节奏区分角色，物件只作辅助。"
        )
    if n >= 5:
        return (
            "人数和脸部：先固定五位独立角色同框，不要裁成单人头像或只突出一张脸；"
            "五张脸都要可见且互不复制，边缘人物也要清楚。"
            "用脸型、眉眼气质、表情习惯、动作姿态、身高体态和互动节奏区分角色；发型、服装和乐器物件只作辅助，不能把同一张真人脸换发色重复使用。"
            "构图上让五人尽量处于相近拍摄距离和相近焦平面，脸部大小接近；不要一人贴近镜头导致脸明显大一倍，不要前景贴脸大头，不要近端广角怼脸或边缘透视拉伸。"
        )

    if wants_five and character_id in {"mygo", "mygo!!!!!", "crychic"}:
        return (
            "人数和脸部：先固定五位独立角色同框，不要裁成单人头像或只突出一张脸；"
            "五张脸都要可见且互不复制，边缘人物也要清楚。"
            "用脸型、眉眼气质、表情习惯、动作姿态、身高体态和互动节奏区分角色；发型、服装和乐器物件只作辅助，不能把同一张真人脸换发色重复使用。"
            "构图上让五人尽量处于相近拍摄距离和相近焦平面，脸部大小接近；不要一人贴近镜头导致脸明显大一倍，不要前景贴脸大头，不要近端广角怼脸或边缘透视拉伸。"
        )
    if wants_four:
        return (
            "人数和脸部：先固定四位独立角色同框，不要裁成单人头像或只突出一张脸；"
            "四张脸都要可见且互不复制，边缘人物也要清楚。"
            "用脸型、眉眼气质、表情习惯、动作姿态、身高体态和互动节奏区分角色，物件只作辅助。"
        )
    if character_id == "ave mujica" and wants_three or wants_three:
        return (
            "人数和脸部：先固定三位独立角色同框，不要裁成单人头像或只突出一张脸；"
            "三张脸都要可见且互不复制，用脸型、发型轮廓、表情习惯、站位和动作分工区分角色。"
        )
    if wants_two:
        return (
            "人数和脸部：先固定两位独立角色同框，不要裁成单人头像；"
            "两张脸都要可见且互不复制，用脸型、发型轮廓、表情习惯、站位和动作分工区分角色。"
        )
    if has_explicit_multi_character:
        explicit_character_count = len([token for token in re.split(r"\s*(?:\+|/|、|,|，|&|和)\s*", character.strip()) if token])
        if explicit_character_count == 2:
            return (
                "人数和脸部：先固定两位独立角色同框，不要裁成单人头像；"
                "两张脸都要可见且互不复制，用脸型、发型轮廓、表情习惯、站位和动作分工区分角色。"
            )
        if explicit_character_count == 3:
            return (
                "人数和脸部：先固定三位独立角色同框，不要裁成单人头像或只突出一张脸；"
                "三张脸都要可见且互不复制，用脸型、发型轮廓、表情习惯、站位和动作分工区分角色。"
            )
        if explicit_character_count == 4:
            return (
                "人数和脸部：先固定四位独立角色同框，不要裁成单人头像或只突出一张脸；"
                "四张脸都要可见且互不复制，边缘人物也要清楚。"
                "用脸型、眉眼气质、表情习惯、动作姿态、身高体态和互动节奏区分角色，物件只作辅助。"
            )
        return (
            "人数和脸部：先固定所有登场角色同框，不要裁成单人头像或只突出一张脸；"
            "每个角色都有独立可见的脸部、发型轮廓、表情和动作分工，不能把同一张真人脸换发色重复使用。"
        )
    return ""


def build_character_face_guide(character: str, scene: str = "", compact: bool = False) -> str:
    names = resolve_face_guide_characters(character, scene)
    if not names:
        return ""

    guide = CHARACTER_FACE_GUIDE_SHORT if compact else CHARACTER_FACE_GUIDE
    lines = [guide[name] for name in names if name in guide]
    if not lines:
        return ""

    if len(lines) == 1:
        return "角色脸部锁定：" + lines[0]

    prefix = (
        "角色分槽锁定：先把每个人当成不同演员 casting，再生成环境；"
        "先区分每个人的脸型轮廓、眉眼习惯、下半张脸、肩颈姿态和表情反应，再锁发型发色；"
        "人物本身的辨识优先，发型、服装和道具只作辅助，不能把同一张真人脸换发色或换道具重复使用。"
    )
    if compact:
        return prefix + " " + "；".join(lines)
    return prefix + "\n" + "\n".join(f"- {line}" for line in lines)


def resolve_face_guide_characters(character: str, scene: str = "") -> list[str]:
    text = f"{character}\n{scene}"
    character_id = character.strip().lower()
    scene_lower = scene.lower()
    resolved: list[str] = []

    # Parse explicit character tokens first — these are authoritative.
    explicit_parsed: list[str] = []
    for token in re.split(r"\s*(?:\+|/|、|,|，|&|和)\s*", character.strip()):
        canonical = CHARACTER_ALIASES.get(token, token)
        if canonical in CHARACTER_FACE_GUIDE:
            explicit_parsed.append(canonical)

    if explicit_parsed:
        resolved.extend(explicit_parsed)
        # Still allow group-guide expansion when character matches a group id
        # (e.g. character="MyGO"), but skip scene-text name/alias scanning
        # to prevent false matches like "灯火" → "灯" → "高松灯".
        for group_name, names in GROUP_FACE_GUIDE.items():
            group_id = group_name.lower()
            if character_id == group_id:
                scene_members = _resolve_scene_members(character, scene)
                if scene_members:
                    resolved.extend(scene_members)
                elif has_any_keyword(text, ("全员", "五人", "五位", "团队", "群像", "同框", "乐队", "成员")):
                    resolved.extend(names)
        return dedupe_names(resolved)

    # Fallback: character not explicitly resolved — scan text for names/aliases.
    for group_name, names in GROUP_FACE_GUIDE.items():
        group_id = group_name.lower()
        if character_id == group_id:
            scene_members = _resolve_scene_members(character, scene)
            if scene_members:
                resolved.extend(scene_members)
            elif has_any_keyword(text, ("全员", "五人", "五位", "团队", "群像", "同框", "乐队", "成员")):
                resolved.extend(names)
        elif group_id in scene_lower and has_any_keyword(scene, ("五人", "五位", "团队", "群像", "同框", "乐队")):
            resolved.extend(names)

    for name in CHARACTER_FACE_GUIDE:
        if name in text:
            resolved.append(name)

    for alias, canonical in CHARACTER_ALIASES.items():
        if alias.lower() in text.lower():
            resolved.append(canonical)

    return dedupe_names(resolved)


def dedupe_names(names: list[str]) -> list[str]:
    result = []
    seen = set()
    for name in names:
        if name in seen:
            continue
        result.append(name)
        seen.add(name)
    return result


def extract_query_terms(query: str, specs_dir: Path) -> set[str]:
    lower = query.lower()
    terms: set[str] = set()

    for keyword, aliases in CONTEXT_ALIASES.items():
        if keyword.lower() in lower:
            terms.add(keyword.lower())
            terms.update(alias.lower() for alias in aliases)

    index_path = specs_dir / "characters" / "index.json"
    if index_path.exists():
        for name, filename in read_json(index_path).items():
            if len(name) > 1 and name.lower() in lower:
                terms.add(name.lower())
                terms.add(Path(filename).stem.lower())

    for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_+-]*", query):
        if len(token) > 1:
            terms.add(token.lower())

    for chunk in re.split(r"[，,。；;\s/+\-&]+", query):
        chunk = chunk.strip().lower()
        if 1 < len(chunk) <= 12:
            terms.add(chunk)

    return {term for term in terms if term}


def retrieve_context_snippets(specs_dir: Path, query: str, max_snippets: int = 6) -> list[ContextSnippet]:
    terms = extract_query_terms(query, specs_dir)
    if not terms:
        return []

    snippets: list[ContextSnippet] = []
    for relative_path in CONTEXT_FILES:
        path = specs_dir / relative_path
        if not path.exists():
            continue
        snippets.extend(score_markdown_blocks(path, specs_dir, terms))

    snippets = [snippet for snippet in snippets if snippet.score > 0]
    snippets.sort(key=lambda snippet: (-snippet.score, snippet.source, snippet.line))

    selected: list[ContextSnippet] = []
    seen: set[str] = set()
    for snippet in snippets:
        key = normalize_snippet_text(snippet.text)
        if key in seen:
            continue
        selected.append(snippet)
        seen.add(key)
        if len(selected) >= max_snippets:
            break
    return selected


def score_markdown_blocks(path: Path, specs_dir: Path, terms: set[str]) -> list[ContextSnippet]:
    blocks: list[ContextSnippet] = []
    current_heading = ""
    for line_number, raw_line in enumerate(read_text(path).splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            current_heading = line.lstrip("#").strip()
            continue

        text = clean_markdown_line(line)
        if not text or len(text) < 8:
            continue

        block = f"{current_heading}：{text}" if current_heading else text
        score = score_text(block, terms)
        if score <= 0:
            continue
        blocks.append(
            ContextSnippet(
                source=str(path.relative_to(specs_dir)),
                line=line_number,
                text=trim_text(block, 320),
                score=score,
            )
        )
    return blocks


def clean_markdown_line(line: str) -> str:
    if line.startswith("- "):
        line = line[2:].strip()
    elif line.startswith("|"):
        cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
        line = "；".join(cell for cell in cells if cell and set(cell) != {"-"})

    line = re.sub(r"`([^`]+)`", r"\1", line)
    line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
    line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
    return line.strip()


def score_text(text: str, terms: set[str]) -> int:
    lower = text.lower()
    score = 0
    for term in terms:
        if term in lower:
            score += 4 if len(term) <= 2 else 8
    if "prompt" in lower or "可复用" in lower or "使用规则" in lower:
        score += 2
    return score


def normalize_snippet_text(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def trim_text(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def compact_color_palette(text: str) -> str:
    text = re.sub(r"\s+", "", (text or "").strip())
    default = re.sub(r"\s+", "", DEFAULT_COLOR_PALETTE)
    if not text or text == default:
        return (
            "正常偏明亮曝光，干净偏暖肤色，角色发色和服装色块清楚；"
            "清透轻修图，可爱优先于普通写实；克制/安静只控制表情和动作，不要全局冷灰低饱和或低曝光。"
        )
    return trim_text(text, 180)


def split_context_snippets(snippets: list[ContextSnippet]) -> tuple[list[str], list[str], list[str]]:
    identity: list[str] = []
    translation: list[str] = []
    relationship: list[str] = []
    for snippet in snippets:
        text = snippet.text
        source = snippet.source.lower()
        lowered = text.lower()
        if "realized_good_results" in source or "realized" in source or "现实化" in text or "真人" in text or "材质" in text:
            translation.append(text)
        elif "visual_refs" in source or "原作" in text or "身份" in text or "角色相似度" in text:
            identity.append(text)
        else:
            relationship.append(text)
    return identity[:4], translation[:4], relationship[:4]


SCENE_INCOMPATIBLE_SNIPPET_RULES = (
    (("舞台", "Live House", "live", "演出", "麦克风", "主唱近景"), ("舞台", "live", "Live", "演出", "麦克风", "主唱")),
    (("雨", "雨夜", "湿地", "透明伞", "墓园", "墓碑"), ("雨", "雨夜", "雨后", "透明伞", "墓", "墓园", "墓碑")),
    (("直播", "弹幕", "电脑屏幕", "同屏", "耳机"), ("直播", "弹幕", "电脑", "屏幕", "连麦", "直播房")),
    (("沙滩", "泳装", "海滩", "浪边"), ("沙滩", "泳装", "海滩", "海边", "浪边", "沿海")),
)


def filter_scene_compatible_snippets(scene: str, snippets: list[str]) -> list[str]:
    return [snippet for snippet in snippets if scene_allows_snippet(scene, snippet)]


def scene_allows_snippet(scene: str, snippet: str) -> bool:
    for snippet_keywords, scene_keywords in SCENE_INCOMPATIBLE_SNIPPET_RULES:
        if has_any_keyword(snippet, snippet_keywords) and not has_any_keyword(scene, scene_keywords):
            return False
    return True


def build_copy_prompt(
    record: dict,
    theme: str,
    profile: PlatformProfile,
    aspect_ratio: str,
    snippets: list[ContextSnippet],
) -> str:
    character = record.get("character") or "未指定主体"
    scene = record.get("scene") or theme
    # Sanitize scene/theme for character-specific feature conflicts
    scene, _scene_warnings = sanitize_theme_for_character(scene, character)
    mood = record.get("mood") or ""
    shot = record.get("shot") or ""
    lighting = record.get("lighting") or ""
    color_palette = record.get("color_palette") or infer_scene_fields(scene).get("color_palette") or DEFAULT_COLOR_PALETTE
    reference_images = record.get("reference_images") or []
    reference_strategy_line = build_reference_strategy_line(reference_images)
    compact = False

    character_snippets, translation_snippets, relationship_snippets = split_context_snippets(snippets)
    character_snippets = filter_scene_compatible_snippets(scene, character_snippets)
    translation_snippets = filter_scene_compatible_snippets(scene, translation_snippets)
    relationship_snippets = filter_scene_compatible_snippets(scene, relationship_snippets)
    reference_line = "；".join(
        f"{image['id']}（{reference_priority_label(image)}）：{trim_text(image.get('notes', ''), 72)}"
        for image in reference_images[:5]
    )
    face_lock = infer_group_face_lock(character, scene)
    face_guide = build_character_face_guide(character, scene, compact=compact or profile.prefers_compact)
    mood_line = mood or "温柔日常、人物关系自然、可爱优先"
    shot_line = shot or "优先保证人物脸部识别、表情差异和群像可辨识性的自然抓拍中景"
    lighting_line = lighting or "让脸部清楚、肤色自然、环境只作为托举人物的柔和现场光"
    palette_line = compact_color_palette(color_palette)

    # CUTE_ANCHOR lookup — for single-character prompts only
    resolved_names = resolve_face_guide_characters(character, scene)
    cute_anchors = [CHARACTER_CUTE_ANCHOR[n] for n in resolved_names if n in CHARACTER_CUTE_ANCHOR]
    cute_anchor = "；".join(cute_anchors) if len(cute_anchors) == 1 else ""

    if profile.id == "midjourney":
        parts = [
            scene,
            f"{character}",
            "character-first realistic social media photo, as if the anime character truly exists in real life, preserve face identity, temperament, expression, and group readability before environment detail",
            face_lock,
            face_guide,
            cute_anchor,
            shot_line,
            lighting_line,
            mood_line,
            "cute East Asian high-school realism, natural skin texture, normal-to-bright exposure, preserved character hair colors, premium natural character styling, no gray wash, no anime face, no cheap cosplay",
        ]
        if character_snippets:
            parts.append("identity anchors: " + "; ".join(character_snippets[:2]))
        if translation_snippets:
            parts.append("realism translation: " + "; ".join(translation_snippets[:1]))
        if relationship_snippets:
            parts.append("relationship support: " + "; ".join(relationship_snippets[:1]))
        if reference_strategy_line:
            parts.append(reference_strategy_line)
        if aspect_ratio:
            parts.append(f"--ar {aspect_ratio}")
        return ", ".join(part for part in parts if part)

    lines = [
        f"生成一张 {aspect_ratio} 的社交媒体日常打卡风格照片，现实化照片质感。",
        f"主题：{scene}",
        f"主体/角色：{character}",
        "人物优先原则：先锁定角色脸型轮廓、眉眼神态、表情习惯、肩颈姿态和互动节奏，再生成环境；目标是让角色如果真实存在就应该长成这样，转译成可信真人皮肤、鼻梁、嘴唇、发丝和摄影光线，不把角色改写成通用漂亮脸，也不把真实感压成普通路人感。角色身份、脸部气质、表情差异、群像可辨识性占主要权重。",
        "年龄/骨相：东亚高中少女感，柔和圆润青春骨相；保存级社交照片质感，圆软脸、清透漂亮、可爱优先、非普通路人。不要成熟骨相、高颧骨、强下颌线、法令纹或成人化面部结构。",
    ]
    if face_lock:
        lines.append(face_lock)
    if face_guide:
        lines.append(face_guide)
    if cute_anchor:
        lines.append(f"美貌与可爱优先：{cute_anchor}")
    lines.append(f"人物目标：{mood or infer_scene_fields(scene).get('mood') or '温柔日常、人物关系自然、可爱优先'}")
    lines.append(f"构图和镜头：{shot_line}")
    if relationship_snippets:
        lines.append("关系/场景辅助：" + trim_text("；".join(relationship_snippets[:1]), 180))
    lines.append(
        "动作要求：单张图只抓一个明确瞬间，用视线、距离、递物、自拍、整理头发、看手机、围桌或乐器动作表达关系；不要空洞站桩。"
    )
    lines.append(
        "单图硬约束：只生成一张完整独立照片，只表现一个地点、一个时间点、一个完整瞬间；严禁拼贴画、多宫格、九宫格、分格排版、contact sheet、film strip 或把多张照片排列在同一画布里。"
    )
    lines.append(f"身体结构：{body_integrity_guardrail(scene)}")
    lines.append(f"光线：{lighting_line}")
    lines.append(
        "环境服务原则：让环境只提供必要的关系线索、空间层次和生活痕迹；只保留能帮助人物成立的物件，不要让背景、道具或光效挤压脸部和人物互动。"
    )
    lines.append(f"色彩和曝光：{palette_line}")
    if character_snippets:
        lines.append("人物锚点：" + trim_text("；".join(character_snippets[:1]), 180))
    if translation_snippets:
        lines.append("现实化转译重点：" + trim_text("；".join(translation_snippets[:1]), 180))
    if reference_strategy_line:
        lines.append(reference_strategy_line)
    if reference_line:
        lines.append(
            "参考图用途："
            + reference_line
            + "。二次元/原作图优先回答‘谁是谁’，现实化样张只回答‘怎样转成可信真人照片’；不要复刻原图文字、logo、版式或截图质感。"
        )
    lines.append(
        "整体风格：真实照片比例，清透轻修图，可爱优先于普通写实；角色符号可以清楚但材质必须真实，像角色本人进入现实生活，而不是廉价 cosplay 或普通 coser 照；克制、安静或沉默只通过表情和动作表达，不转换成全局冷灰低饱和、低曝光或疲惫滤镜。"
    )
    # Avoid block: only items NOT already covered by CHARACTER_FIRST_NEGATIVE_RULES,
    # BODY_INTEGRITY_NEGATIVE, or negative_rules.md
    avoid_unique = [
        "环境压过人物",
        "拼贴画",
        "多宫格",
        "九宫格",
        "contact sheet",
        "动漫脸",
        "蜡像皮肤",
        "整齐站桩",
        "可读乱码文字",
        "水印",
        "多人克隆同脸",
        "僵硬列队站姿",
        "所有人相同表情",
    ]
    lines.append("避免：" + "、".join(avoid_unique + list(BODY_INTEGRITY_NEGATIVE)) + "。")
    return "\n".join(lines)


def should_generate_scene_list_variants(theme: str) -> bool:
    """Return True when the theme text enumerates multiple distinct scene prompts."""
    # Match "N个不同X的Y场景" pattern (e.g. "5个不同城市的可爱打卡场景")
    if re.search(r"\d+个不同", theme):
        return True
    if has_any_keyword(
        theme,
        (
            "十组", "十张", "十个", "十种",
            "多组", "多张", "多个", "多种",
            "覆盖", "场景覆盖", "场景包含",
            "5组", "6组", "7组", "8组", "9组",
            "5个", "6个", "7个", "8个", "9个", "10个",
        ),
    ):
        return True
    if re.search(r"[\(（]\d+[\)）]", theme):
        return True
    return False


def should_generate_single_character_variants(theme: str) -> bool:
    """Backward-compatible alias for old callers."""
    return should_generate_scene_list_variants(theme)


_SCENE_LIST_SPLIT_RE = re.compile(r"[、，,；;]")
_SCENE_TRAILING_GLOBAL_MARKERS = (
    "每张",
    "每一张",
    "每个画面",
    "每幅",
    "整体",
    "卖萌来自",
    "严禁",
    "注意",
    "要求",
)


def _trim_scene_desc(text: str) -> str:
    scene = text.strip(" \n\t。；;、.")
    for marker in _SCENE_TRAILING_GLOBAL_MARKERS:
        marker_index = scene.find(marker)
        if marker_index > 0:
            before = scene[:marker_index].rstrip(" \n\t。；;、.")
            if before:
                scene = before
    return scene


def _parse_numbered_scenes(theme: str) -> list[str]:
    """Fallback: extract scenes delimited by (1), (2), (3) etc. when no marker is found."""
    matches = list(re.finditer(r'[\(（](\d+)[\)）]', theme))
    if len(matches) < 2:
        return []

    scenes: list[str] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(theme)
        scene = _trim_scene_desc(theme[start:end])
        if scene:
            scenes.append(scene)
    return scenes if len(scenes) >= 2 else []


def _parse_scene_list(theme: str) -> list[str]:
    """Extract individual scene descriptions from a multi-scene theme text."""
    markers = [
        "十组日常场景：", "十个场景：", "十个场景:",
        "场景覆盖：", "场景覆盖:", "场景包含：", "场景包含:",
        "多场景：", "多组场景：", "场景列表：",
        "场景：", "场景:",
    ]
    for marker in markers:
        idx = theme.find(marker)
        if idx < 0:
            continue
        tail = theme[idx + len(marker):]
        period_positions = [m.start() for m in re.finditer("。", tail)]
        end_candidates = period_positions + [len(tail)]

        # Approach 1: single-block (handles numbered scenes spanning "。")
        single_best: list[str] = []
        for end in end_candidates:
            scene_block = tail[:end].strip()
            if not scene_block:
                continue
            numbered_parts = _parse_numbered_scenes(scene_block)
            if len(numbered_parts) > len(single_best):
                single_best = numbered_parts
            if len(single_best) < 2:
                parts = [_trim_scene_desc(s) for s in _SCENE_LIST_SPLIT_RE.split(scene_block) if _trim_scene_desc(s)]
                if len(parts) > len(single_best):
                    single_best = parts

        # Approach 2: multi-sentence (handles "。"-separated scene blocks)
        multi_best: list[str] = []
        for end in end_candidates:
            scene_block = tail[:end].strip()
            if not scene_block:
                continue
            all_scenes: list[str] = []
            for sentence in scene_block.split("。"):
                sentence = sentence.strip()
                if not sentence:
                    continue
                # Strip marker prefix if sentence starts with one
                for m in markers:
                    if sentence.startswith(m):
                        sentence = sentence[len(m):].strip()
                        break
                if not sentence:
                    continue
                numbered = _parse_numbered_scenes(sentence)
                if len(numbered) >= 2:
                    all_scenes.extend(numbered)
                else:
                    for part in _SCENE_LIST_SPLIT_RE.split(sentence):
                        trimmed = _trim_scene_desc(part)
                        if trimmed:
                            all_scenes.append(trimmed)
            if len(all_scenes) > len(multi_best):
                multi_best = all_scenes

        # Use whichever approach yields more scenes
        result = single_best if len(single_best) >= len(multi_best) else multi_best
        if result:
            result = [s for s in result if not s.startswith(("每张", "每组", "每幅"))]
            if result:
                return result
    return _parse_numbered_scenes(theme)


_SCENE_INFERENCE_KEYWORDS: dict[str, list[str]] = {
    "城市": [
        "北京", "上海", "广州", "深圳", "成都", "杭州", "南京", "重庆",
        "武汉", "西安", "厦门", "长沙", "青岛", "苏州", "天津", "大连",
    ],
    "时间段": ["清晨", "上午", "午后", "傍晚", "黄昏", "夜晚"],
    "季节": ["春天", "夏天", "秋天", "冬天"],
    "天气": ["晴天", "多云", "雨天", "雪天", "雾天"],
    "地点": ["公园", "街角", "咖啡馆", "书店", "海边", "天台", "小巷", "广场"],
}

_INFER_SCENE_RE = re.compile(r"(\d+)个不同(.+?)的(.+?)场景")


def _infer_scenes_from_theme(theme: str) -> list[str]:
    """从 "N个不同X的Y场景" 格式推断具体场景列表。

    例如 "5个不同城市的可爱打卡场景" → ["北京的可爱打卡", "上海的可爱打卡", ...]
    """
    m = _INFER_SCENE_RE.search(theme)
    if not m:
        return []
    n = int(m.group(1))
    category = m.group(2)  # e.g. "城市"
    scene_type = m.group(3)  # e.g. "可爱打卡"

    candidates: list[str] | None = None
    for key, values in _SCENE_INFERENCE_KEYWORDS.items():
        if key in category:
            candidates = values
            break

    if not candidates:
        return []

    import random
    selected = random.sample(candidates, min(n, len(candidates)))
    return [f"{city}的{scene_type}" for city in selected]


# Canonical feature overrides: when theme text contains conflicting descriptions,
# these replacements ensure the correct character features win.
# Format: character_name -> [(pattern_to_detect, replacement, reason)]
CANONICAL_FEATURE_OVERRIDES: dict[str, list[tuple[str, str, str]]] = {
    "若叶睦": [
        (r"灰绿色?眼眸?", "金棕眼", "睦的正确瞳色是金棕色（golden-brown eyes）"),
        (r"灰绿眼", "金棕眼", "睦的正确瞳色是金棕色"),
        (r"gray-green eye", "golden-brown eyes", "睦的正确瞳色是 golden-brown"),
        (r"中长发", "及腰长发", "睦的设定是顺滑及腰长发"),
        (r"温柔", "慢半拍发呆感", "睦的气质核心是植物性安静/慢半拍，不是温柔（温柔是素世的特征）"),
    ],
}


def sanitize_theme_for_character(theme: str, character: str) -> tuple[str, list[str]]:
    """Check theme text for descriptions conflicting with character's canonical features.

    Returns (sanitized_theme, list_of_warnings).
    """
    if not theme or not character:
        return theme, []
    overrides = CANONICAL_FEATURE_OVERRIDES.get(character)
    if not overrides:
        return theme, []
    result = theme
    warnings: list[str] = []
    for pattern, replacement, reason in overrides:
        match = re.search(pattern, result, re.IGNORECASE)
        if match:
            result = re.sub(pattern, replacement, result, count=1, flags=re.IGNORECASE)
            warnings.append(f"[角色设定纠偏] {character}：'{match.group()}' → '{replacement}'（{reason}）")
    return result, warnings


# Scene temperament translations: when a scene requires outgoing/playful expressions
# that conflict with a character's core temperament, translate the action description.
# Format: character_name -> [(trigger_pattern, replacement_description)]
SCENE_TEMPERAMENT_TRANSLATIONS: dict[str, list[tuple[str, str]]] = {
    "若叶睦": [
        (r"吐[舌着]头?", "轻微困惑地抿嘴，像被辣到不知所措"),
        (r"吐舌", "轻微困惑地抿嘴，像被辣到不知所措"),
        (r"张嘴|张口", "小口咬，犹豫着递过来的样子"),
        (r"开心[的地]?笑|大笑|开怀", "很小的笑意，嘴角微微上扬"),
        (r"[举比][Vv]|比[Vv]|剪刀手", "手指犹豫地比出V，慢半拍反应"),
        (r"卖萌|撒娇|嘟嘴", "迟钝的自然反应，被同伴拍到的无意识可爱"),
        (r"对镜头微笑|对着镜头笑|对镜头[微]?笑", "被镜头拍到时慢半拍转头，嘴角有一丝很轻的笑意"),
    ],
}


def translate_scene_for_character(scene_desc: str, character: str) -> str:
    """Translate scene actions that conflict with a character's core temperament.

    For characters like Mutsumi whose identity relies on quiet/delayed reactions,
    outgoing scene actions are re-interpreted to match their personality.
    """
    if not scene_desc or not character:
        return scene_desc
    translations = SCENE_TEMPERAMENT_TRANSLATIONS.get(character)
    if not translations:
        return scene_desc
    result = scene_desc
    for pattern, replacement in translations:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result


def _extract_base_theme(theme: str) -> str:
    """Return the theme text before the scene enumeration block."""
    markers = [
        "十组日常场景：", "十个场景：", "十个场景:",
        "场景覆盖：", "场景覆盖:", "场景包含：", "场景包含:",
        "多场景：", "多组场景：", "场景列表：",
        "场景：", "场景:",
    ]
    cut = len(theme)
    for marker in markers:
        idx = theme.find(marker)
        if idx >= 0 and idx < cut:
            cut = idx
    if cut == len(theme):
        stripped = theme.strip()
        if re.match(r'^\(\d+\)|^\d+[\.\)、]|^[一二三四五六七八九十][、.]', stripped):
            return ""
        if len(stripped) > 300 and re.search(r'\(\d+\)', stripped):
            return ""
        return theme
    base = theme[:cut].strip()
    if base.endswith("。") or base.endswith("."):
        base = base[:-1].strip()
    return base


def render_single_character_quality_prompt(
    aspect_ratio: str,
    character: str,
    scene_desc: str,
    base_theme: str,
    face_guide: str,
    mood: str,
    lighting: str,
    color_palette: str,
    shot: str,
    negative_hints: str = "",
    cute_anchor: str = "",
) -> str:
    """5-capsule short-strong prompt for single-character single-image generation.

    Structure: declaration -> character identity -> beauty/cute -> scene+action -> negative
    """
    aspect_label = aspect_ratio or "3:4"

    # Capsule 1: Declaration — what this is
    parts: list[str] = [
        f"生成一张 {aspect_label} 的现实化社交媒体日常照片。",
    ]

    # Capsule 2: Character identity — who this is (face_guide includes name + anchors)
    if face_guide:
        parts.append(face_guide)

    # Capsule 3: Beauty/cute — character-specific quality target, front-loaded
    if cute_anchor:
        parts.append(f"美貌与可爱优先：{cute_anchor}")
    else:
        parts.append(
            "美貌与可爱优先：保存级社交照片，第一眼像角色本人，"
            "圆软青春脸、清透漂亮、可爱优先、非普通路人；"
            "轻修图但保留自然皮肤纹理和光感。"
        )

    # Capsule 4: Scene + action + tech — single scene, single moment
    # Translate scene actions that conflict with character temperament
    scene_desc = translate_scene_for_character(scene_desc, character)
    if base_theme and len(base_theme) < 100:
        parts.append(f"项目背景：{base_theme}")
    parts.extend([
        f"本张场景：{scene_desc}",
        f"情绪：{mood}",
        f"构图：{shot}，突出人物主体。",
        f"光线：{lighting}",
    ])
    if color_palette:
        parts.append(f"色彩：{color_palette}")
    parts.append(f"身体结构：{body_integrity_guardrail(scene_desc)}")

    # Capsule 5: Compact negative — character-specific + key red lines
    neg_parts: list[str] = []
    if negative_hints:
        neg_parts.append(negative_hints)
    neg_parts.extend([
        "严禁：拼贴画/多宫格/九宫格/分格排版/contact sheet/film strip/多张照片排列",
        "严禁：幼童化、猫耳/兽耳、cosplay假发感、动漫渲染、蜡像皮肤",
        "不要欧美成熟女性、高挑宽肩、中性帅哥",
    ])
    neg_parts.extend(BODY_INTEGRITY_NEGATIVE)
    parts.append("；".join(neg_parts))

    return "\n".join(parts)


def render_scene_list_variant_prompt(
    record: dict,
    aspect_ratio: str,
    character: str,
    scene_desc: str,
    base_theme: str,
    mood: str,
    lighting: str,
    color_palette: str,
    shot: str,
    negative_hints: str = "",
    cute_anchor: str = "",
) -> str:
    """Prompt for one explicitly listed scene, preserving group identity when needed."""
    aspect_label = aspect_ratio or "3:4"
    face_lock = infer_group_face_lock(character, base_theme)
    face_guide = build_character_face_guide(character, base_theme)
    base_summary = trim_text(base_theme, 520)

    parts: list[str] = [
        f"生成一张 {aspect_label} 的现实化社交媒体日常照片。",
        "这是一张单张独立照片，只表现一个地点、一个时间点、一个完整瞬间；不要把标题或编号写进画面。",
    ]
    if base_summary:
        parts.append(f"本组共同设定：{base_summary}")
    if face_lock:
        parts.append(face_lock)
    if face_guide:
        parts.append(face_guide)
    if cute_anchor:
        parts.append(f"美貌与可爱优先：{cute_anchor}")
    else:
        parts.append("美貌与可爱优先：保存级社交照片，第一眼像角色本人，清透漂亮、可爱优先、非普通路人。")
    # Translate scene actions that conflict with character temperament
    scene_desc = translate_scene_for_character(scene_desc, character)
    parts.extend(
        [
            f"本张场景：{scene_desc}",
            f"情绪：{mood}",
            f"构图：{shot}，突出人物主体和脸部识别。",
            f"光线：{lighting}",
        ]
    )
    if color_palette:
        parts.append(f"色彩：{color_palette}")
    parts.append(f"身体结构：{body_integrity_guardrail(scene_desc)}")

    neg_parts: list[str] = []
    if negative_hints:
        neg_parts.append(negative_hints)
    neg_parts.extend(
        [
            "严禁：拼贴画/多宫格/九宫格/分格排版/contact sheet/film strip/多张照片排列",
            "严禁：幼童化、猫耳/兽耳、cosplay假发感、动漫渲染、蜡像皮肤",
            "不要让其他场景、城市或动作混入本张画面",
        ]
    )
    neg_parts.extend(BODY_INTEGRITY_NEGATIVE)
    parts.append("；".join(neg_parts))
    return "\n".join(parts)


_SCENE_LIGHTING_RULES: list[tuple[list[str], str]] = [
    (["夜", "灯火", "灯笼", "夜市", "夜色", "灯下"], "夜间暖灯光，灯笼/街灯形成暖色层次，人脸受暖光照亮"),
    (["雨", "细雨", "烟雨", "雨中", "雨后"], "阴天柔光，雨水漫反射的柔和氛围光，不要硬闪光"),
    (["傍晚", "夕阳", "黄昏", "蓝调"], "黄金时刻暖光，夕阳余晖或蓝调时段的城市氛围光"),
    (["清晨", "晨", "朝阳"], "清晨柔光，干净清透的晨间自然光"),
    (["室内", "茶馆", "咖啡", "教室", "房间"], "室内自然光或暖色灯光，窗光为主，不要硬顶灯"),
    (["舞台", "演出", "Live House"], "舞台逆光或侧光，有氛围但面部仍清楚"),
]


def _infer_scene_lighting(scene_desc: str, default: str = "") -> str:
    """Infer lighting from scene description keywords. Returns empty string if no match."""
    for keywords, lighting in _SCENE_LIGHTING_RULES:
        for kw in keywords:
            if kw in scene_desc:
                return lighting
    return default


def build_single_character_scene_variants(
    record: dict,
    theme: str,
    aspect_ratio: str,
    count: int = 3,
) -> list[dict]:
    scenes = _parse_scene_list(theme)
    if not scenes:
        scenes = _infer_scenes_from_theme(theme)
    if not scenes:
        return []

    character = record.get("character") or "主体"
    mood = record.get("mood") or "自然可爱"
    lighting = record.get("lighting") or "自然日光和柔暖日常光，清透明亮"
    color_palette = record.get("color_palette") or ""
    shot = record.get("shot") or "中景和半身为主"
    face_guide = build_character_face_guide(character)
    base_theme = _extract_base_theme(theme)

    # Sanitize base_theme for character-specific feature conflicts
    if base_theme:
        base_theme, theme_warnings = sanitize_theme_for_character(base_theme, character)
        for warning in theme_warnings:
            print(warning)

    resolved_names = resolve_face_guide_characters(character)
    char_negs = extract_character_specific_negatives(resolved_names)
    negative_hints = "、".join(char_negs) if char_negs else ""

    # Look up character-specific cute anchor for Capsule 3 — merge all resolved characters
    cute_anchors = []
    for name in resolved_names:
        if name in CHARACTER_CUTE_ANCHOR:
            cute_anchors.append(CHARACTER_CUTE_ANCHOR[name])
    cute_anchor = "；".join(cute_anchors)

    variants: list[dict] = []
    limit = len(scenes) if count <= 0 else count
    for index, scene_desc in enumerate(scenes[:limit], 1):
        title = f"场景{index:02d}: {scene_desc[:24]}"
        # Per-scene lighting: try to infer from scene keywords, fall back to default
        scene_lighting = _infer_scene_lighting(scene_desc, default=lighting)
        if len(resolved_names) <= 1:
            variant_prompt = render_single_character_quality_prompt(
                aspect_ratio=aspect_ratio,
                character=character,
                scene_desc=scene_desc,
                base_theme=base_theme,
                face_guide=face_guide,
                mood=mood,
                lighting=scene_lighting,
                color_palette=color_palette,
                shot=shot,
                negative_hints=negative_hints,
                cute_anchor=cute_anchor,
            )
        else:
            variant_prompt = render_scene_list_variant_prompt(
                record=record,
                aspect_ratio=aspect_ratio,
                character=character,
                scene_desc=scene_desc,
                base_theme=base_theme,
                mood=mood,
                lighting=scene_lighting,
                color_palette=color_palette,
                shot=shot,
                negative_hints=negative_hints,
                cute_anchor=cute_anchor,
            )
        variants.append(
            {
                "title": title,
                "scene": scene_desc,
                "time": scene_lighting,
                "focus": f"单场景聚焦：{scene_desc}",
                "guardrails": [
                    "不要拼贴画/九宫格/多格排版",
                    "只生成单张照片",
                    "不要猫耳/幼童化/cosplay假发感",
                    "不要欧美成熟女性/高挑宽肩/中性帅哥",
                ],
                "prompt": variant_prompt,
            }
        )
    return variants


def build_variant_prompts(
    record: dict,
    theme: str,
    aspect_ratio: str,
    count: int = 3,
) -> list[dict]:
    scene = record.get("scene") or theme
    character = record.get("character") or "主体"
    if _parse_scene_list(theme):
        return build_single_character_scene_variants(record, theme, aspect_ratio, count=count)
    if should_generate_storyboard_variants(character, scene):
        pass  # fall through to blueprint generation below
    elif should_generate_scene_list_variants(theme):
        return build_single_character_scene_variants(record, theme, aspect_ratio, count=count)
    else:
        return []

    blueprints = build_storyboard_blueprints(character, scene)
    priorities = [
        ("人物保真优先", "先锁脸部识别、气质差异和群像可辨识性，环境只保留最低限度。"),
        ("关系表达优先", "保持人物准确前提下，强调视线、距离、递物和动作关系。"),
        ("人物环境平衡", "人物仍然优先，同时补充必要空间线索和生活物件。"),
        ("氛围增强版本", "只有在人物已稳的前提下，才允许增加更强环境与光线氛围。"),
    ]
    variants: list[dict] = []
    limit = len(blueprints) if count <= 0 else count
    for index, blueprint in enumerate(blueprints[:limit], 1):
        mode, directive = priorities[min(index - 1, len(priorities) - 1)]
        variants.append(render_storyboard_variant(record, scene, aspect_ratio, index, blueprint, mode, directive))
    return variants


def should_generate_storyboard_variants(character: str, scene: str) -> bool:
    text = f"{character}\n{scene}"
    return has_any_keyword(text, ("旅行", "城市", "海边", "沿海", "车站", "夜市", "街巷", "古镇", "旅馆", "酒店")) and has_any_keyword(
        text, ("五人", "五位", "团队", "群像", "同框", "MyGO", "MyGO!!!!!")
    )


def build_storyboard_blueprints(character: str, scene: str) -> list[dict]:
    variants = [
        {
            "title": "海边步道初到",
            "scene": "海边步道、栏杆、防波堤与远处港区线条",
            "time": "下午自然日光，海风明显",
            "focus": "刚到沿海城市、队形还没完全稳定",
            "action": "爱音回头招呼大家跟上，灯停下看海和栏杆反光，乐奈被远处声音吸引慢半步，素世整理纸袋和饮料，立希看方向和时间",
            "guardrails": ["不要旅游宣传片式大合照", "不要把五个人拍成整齐站桩营业照"],
        },
        {
            "title": "港口观景台停留",
            "scene": "港口观景台、城市海湾、风吹起的衣摆和远处船只",
            "time": "傍晚前的通透侧光",
            "focus": "短暂停下来确认目的地，同时自然分散站位",
            "action": "有人扶栏杆看海，有人检查手机地图，有人按住被风吹乱的纸张或头发，乐奈靠边观察远处动静",
            "guardrails": ["不要 MV 封面感", "不要所有人同时看镜头"],
        },
        {
            "title": "临海电车站等车",
            "scene": "临海电车站台、玻璃、中文站牌氛围、远处海面或堤岸",
            "time": "蓝调时刻与站台混合光",
            "focus": "等待中的安静停顿，不是摆拍",
            "action": "爱音看车次或站牌，灯抱着票据和歌词本安静发呆，素世确认大家是否到齐，立希盯着时刻，乐奈贴近站台边缘听风声",
            "guardrails": ["不要可读大段站牌乱码", "不要把站台拍成广告片"],
        },
        {
            "title": "骑楼街巷边走边聊",
            "scene": "中国沿海城市骑楼街巷、店铺外立面、树影、普通行人和共享单车",
            "time": "白天柔和街景光",
            "focus": "走路中的关系感和自然错位",
            "action": "爱音一边说话一边带路，灯靠近听但动作小，乐奈被边店陈列吸引，素世提醒别落东西，立希在边上控节奏",
            "guardrails": ["不要日式街区冒充中国", "不要空街拍成时尚大片"],
        },
        {
            "title": "便利店门口补给",
            "scene": "便利店门口、冷柜白光、纸袋、饮料、街边栏杆与步行道",
            "time": "傍晚或入夜前后的店铺白光加环境天光",
            "focus": "旅行途中补给后的短暂停顿",
            "action": "素世分饮料和纸袋，爱音检查手机和路线，灯捧着热饮观察门口光影，立希确认下一站时间，乐奈看向远处摊位或街声",
            "guardrails": ["不要便利店广告感", "不要把环境简化成空白门头"],
        },
        {
            "title": "夜市短暂走散后重聚",
            "scene": "夜市街巷、暖色摊灯、蒸汽、湿地反光、中文灯牌氛围",
            "time": "暖灯夜景",
            "focus": "轻微混乱后重新集合的松一口气",
            "action": "爱音举手招呼，灯抱着纸袋明显放松，素世数人头，立希表情不耐烦但放心，乐奈拿着刚买的小东西从边缘回到队伍",
            "guardrails": ["不要拥挤推搡", "不要失去角色性格的夸张肢体戏"],
        },
        {
            "title": "防波堤黄昏看海",
            "scene": "防波堤、石阶、栏杆、海面反光和远处城市光点",
            "time": "黄昏到蓝调过渡时刻",
            "focus": "一天里最安静的一次并肩停留",
            "action": "灯看海面反光，爱音回头看她，素世整理风吹乱的物件，立希站在稍后位置守着队伍节奏，乐奈蹲在边缘听浪声",
            "guardrails": ["不要拍成悲伤 MV 海报", "不要全局冷灰压暗"],
        },
        {
            "title": "小旅馆房间收尾",
            "scene": "小旅馆房间、桌面杂物、票根、纸袋、充电线、窗外夜光",
            "time": "暖色台灯和窗外城市夜光",
            "focus": "一天结束后的复盘和放松",
            "action": "爱音看照片回放，灯整理票根或歌词本，素世归拢伴手礼，立希写第二天路线，乐奈坐在床边抱着包或吃点心",
            "guardrails": ["不要样板间宣传照", "不要五人整齐坐着看镜头"],
        },
    ]
    return variants


def render_storyboard_variant(
    record: dict,
    scene: str,
    aspect_ratio: str,
    index: int,
    blueprint: dict,
    mode: str,
    directive: str,
) -> dict:
    character = record.get("character") or "主体"
    lighting = blueprint["time"]
    color_palette = infer_scene_fields(blueprint["scene"] + "\n" + scene).get("color_palette") or record.get("color_palette") or DEFAULT_COLOR_PALETTE
    face_lock = infer_group_face_lock(character, scene)
    face_guide = build_character_face_guide(character, scene)
    prompt_parts = [
        f"生成一张 {aspect_ratio} 的现实化社交媒体日常照片。",
        f"变体目标：{mode}。{directive}",
        f"上下文：延续同一主题下的人物关系与角色设定，不重写整段故事背景。",
        "人物优先：先保证角色脸部识别、气质差异、主次人物结构和群像可辨识性，再决定环境细节。",
        "年龄/骨相硬约束：所有人物均为15-16岁东亚高中少女，面部必须保留青春期少女的柔和圆润骨相和自然青春气息；不要成熟骨相、高颧骨、强下颌线、法令纹或任何成人化面部结构。可爱感和少女感优先于一切\"真实感\"。",
    ]
    if face_lock:
        prompt_parts.append(face_lock)
    if face_guide:
        prompt_parts.append(face_guide)
    prompt_parts.extend(
        [
            f"人物动作：{blueprint['action']}。",
            f"关系重点：{blueprint['focus']}。",
            f"环境只保留这些必要线索：{blueprint['scene']}。",
            f"时间与光线：{lighting}。",
            f"色彩和曝光：{color_palette}",
            "这是一张单张独立照片，只表现一个地点、一个时间点、一个完整瞬间；不要拼贴、不要多宫格、不要把标题或编号写进画面。",
            "不要让背景、道具、灯光特效或空间复杂度挤压人物脸部和关系阅读。",
            f"身体结构：{body_integrity_guardrail(blueprint['action'] + ' ' + blueprint['scene'])}",
            "防偏航：" + "；".join(blueprint["guardrails"]) + "。",
            "身体负面：" + "、".join(BODY_INTEGRITY_NEGATIVE) + "。",
        ]
    )
    return {
        "title": f"{index:02d} {blueprint['title']}（{mode}）",
        "scene": blueprint["scene"],
        "time": blueprint["time"],
        "focus": blueprint["focus"],
        "guardrails": blueprint["guardrails"],
        "prompt": "\n".join(prompt_parts),
    }


def detect_redundant_character_guidance(prompt: str) -> list[str]:
    if "## 角色设定" not in prompt:
        return []

    section = prompt.split("## 角色设定", 1)[1].split("## 本张图片", 1)[0]
    sections = re.split(r"\n(?=### )", section)
    repeated_names: list[str] = []

    for block in sections:
        block = block.strip()
        if not block.startswith("### "):
            continue

        lines = [line.strip() for line in block.splitlines()]
        name = lines[0][4:].strip()
        bullet_lines = [
            clean_markdown_line(line)
            for line in lines[1:]
            if line.strip().startswith("- ")
        ]
        bullet_lines = [line for line in bullet_lines if len(line) >= 12]
        if len(bullet_lines) < 2:
            continue

        redundant = False
        normalized_seen: set[str] = set()
        keyword_signatures: list[set[str]] = []
        for line in bullet_lines:
            normalized = normalize_snippet_text(line)
            if normalized in normalized_seen:
                redundant = True
                break
            normalized_seen.add(normalized)

            keywords = set(re.findall(r"[A-Za-z]+|[一-龥]{2,}", line.lower()))
            keywords -= {"现实化", "角色", "可爱", "不要", "适合", "画面", "人物", "气质", "动作"}
            if len(keywords) < 3:
                continue
            for existing in keyword_signatures:
                overlap = len(existing & keywords)
                if overlap >= 3 and overlap >= min(len(existing), len(keywords)) - 1:
                    redundant = True
                    break
            if redundant:
                break
            keyword_signatures.append(keywords)

        if redundant:
            repeated_names.append(name)

    if not repeated_names:
        return []
    names = "、".join(repeated_names)
    return [f"角色设定可能存在重复指导：{names}；建议合并同义约束，避免稀释关键现实化锚点。"]


def check_doc_quality(
    record: dict,
    aspect_ratio: str,
    snippets: list[ContextSnippet],
    copy_prompt: str,
    profile: PlatformProfile,
) -> list[str]:
    notes = []
    if not record.get("character"):
        notes.append("未识别到角色/对象；建议用 `--character` 明确主体。")
    if not aspect_ratio:
        notes.append("缺少画幅；建议指定 `--aspect-ratio`。")
    if not record.get("reference_images"):
        notes.append("没有匹配到参考图；如果角色识别重要，建议用 `--refs` 指定。")
    if not snippets:
        notes.append("没有命中素材库片段；可以补充主题关键词，或扩展 specs 中的素材。")
    if profile.prefers_compact and len(copy_prompt) > 1200:
        notes.append("当前平台偏好短 prompt；建议手动删减资料片段后再提交。")
    if len(copy_prompt) < 120:
        notes.append("主 Prompt 偏短；建议补充动作、空间、光线和镜头。")
    if "人物优先原则" not in copy_prompt:
        notes.append("主 Prompt 未显式声明人物优先；建议把角色识别和气质优先级前置。")
    if "环境服务原则" not in copy_prompt:
        notes.append("主 Prompt 没有明确限制环境权重；建议说明环境只负责托举人物。")
    if "主题延续：" in copy_prompt:
        notes.append("当前文档仍带有较重的整段主题复述；建议继续压缩重复故事背景。")
    character = record.get("character", "")
    resolved_names = resolve_face_guide_characters(character, record.get("scene", ""))
    if resolved_names:
        names_in_prompt = [n for n in resolved_names if n in copy_prompt]
        if not names_in_prompt:
            notes.append("角色脸部指南未反映在 Prompt 中；建议用 --character 明确角色名。")
    replacement_chars = sum(1 for ch in copy_prompt if ch == "�")
    if replacement_chars >= 3:
        notes.append("Prompt 中存在 Unicode 替换字符，可能存在编码损坏。")
    notes.extend(detect_redundant_character_guidance(record.get("prompt") or ""))
    return notes


SCENE_NEGATIVE_RULES = (
    (
        ("舞台", "live", "Live", "演出", "麦克风"),
        (
            "舞台图不要变成夸张偶像营业照或海报式摆拍",
        ),
    ),
    (
        ("直播", "屏幕", "弹幕", "电脑"),
        (
            "屏幕画面不要生成可读乱码文字或真实商标",
        ),
    ),
)

CHARACTER_FIRST_NEGATIVE_RULES = (
    "同一张脸换发色重复",
    "脸部融合或角色混淆",
    "主角不突出",
    "边缘人物消失或糊成无脸",
    "廉价假发感",
)

BODY_INTEGRITY_POSITIVE = (
    "每人只有两条手臂、两条腿，双手双脚关系清楚，关节连续自然。"
    "手指数量正确、手掌结构清楚，脚部轮廓完整。"
    "肢体不要和衣服、背景、道具或阴影融合。"
)

BODY_INTEGRITY_NEGATIVE = (
    "多余手臂、多余腿、多余手指、缺手、缺脚",
    "手脚和肢体融合、关节断裂、膝盖或脚踝消失",
    "肢体和衣服、背景或道具融合在一起",
    "手指数目不对、手指畸形、手掌扭曲",
)

_BODY_HIGH_RISK_KEYWORDS = (
    "坐", "蹲", "抱膝", "盘腿", "蜷", "跪", "靠椅", "桌边",
    "草地", "岩石", "台阶", "椅", "桌子",
    "前景", "裁切", "近景", "中近景",
    "吉他包", "乐器包", "背包", "贝斯盒",
    "鞋", "脚", "手",
)


def body_integrity_guardrail(scene_desc: str) -> str:
    """根据场景关键词决定身体约束强度。"""
    base = BODY_INTEGRITY_POSITIVE
    if any(kw in scene_desc for kw in _BODY_HIGH_RISK_KEYWORDS):
        return (
            base
            + " 复杂姿态/遮挡场景加强：关节必须可见且连续，"
            "膝盖弯曲方向正确，脚踝不消失在衣物或阴影里；"
            "允许自然画面裁切但不得裁掉手腕、脚踝、膝盖等关键关节；"
            "遮挡后不能把手脚吞掉、接错或融进衣服/道具/背景。"
        )
    return base


def extract_character_specific_negatives(resolved_names: list[str]) -> list[str]:
    """Extract per-character anti-drift clauses from CHARACTER_FACE_GUIDE.

    Only returns items for single-character prompts; multi-character prompts rely
    on the generic CHARACTER_FIRST_NEGATIVE_RULES to keep the prompt lean.
    """
    if len(resolved_names) != 1:
        return []
    name = resolved_names[0]
    guide = CHARACTER_FACE_GUIDE.get(name, "")
    if "不要" not in guide:
        return []
    dont_section = guide.split("不要", 1)[1]
    items: list[str] = []
    for part in re.split(r"[、，,；;。]", dont_section):
        part = part.strip().rstrip("。；;")
        if part and len(part) >= 3:
            items.append(part)
    return items


def reference_priority_label(image: dict) -> str:
    tier = image.get("reference_tier") or ""
    roles = set(image.get("roles") or [])
    if tier == "realized_translation" or "realized" in roles:
        return "现实化辅助：只转译材质/比例"
    if tier == "context_support":
        return "场景/关系辅助：不覆盖角色身份"
    return "二次元/原作图优先锁定角色相似度"


def build_reference_strategy_line(reference_images: list[dict]) -> str:
    if not reference_images:
        return ""
    identity_count = sum(1 for image in reference_images if image.get("reference_tier") == "identity_anchor")
    context_count = sum(1 for image in reference_images if image.get("reference_tier") == "context_support")
    realized_count = sum(1 for image in reference_images if image.get("reference_tier") == "realized_translation")
    return (
        "参考图权重策略：identity_anchor 回答‘谁是谁’，context_support 只补场景关系，realized_translation 只转译真人质感。"
        f"当前配比 identity={identity_count}, context={context_count}, realized={realized_count}；"
        "如果角色相似度和现实化质感冲突，始终优先角色身份与可爱感。"
    )


def build_negative_prompt(
    specs_dir: Path,
    max_items: int = 12,
    context: str = "",
    character: str = "",
) -> str:
    path = specs_dir / "negative_rules.md"
    if not path.exists():
        return ""

    items = list(CHARACTER_FIRST_NEGATIVE_RULES) if (context or character) else []
    hardcoded_count = len(items)
    items.extend(select_targeted_negative_items(f"{character}\n{context}"))
    if character:
        resolved = resolve_face_guide_characters(character)
        items.extend(extract_character_specific_negatives(resolved))
    if context or character:
        items.extend(BODY_INTEGRITY_NEGATIVE)
    for line in read_text(path).splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        item = line[2:].strip().rstrip("。")
        if any(term in item for term in NEGATIVE_PROMPT_OMIT_TERMS):
            continue
        if item:
            items.append(item)
        scene_items = items[hardcoded_count:]
        if len(unique_items(scene_items)) >= max_items:
            break
    all_items = unique_items(items)
    return "、".join(all_items[:hardcoded_count + max_items])


def select_targeted_negative_items(context: str) -> list[str]:
    if not context:
        return []
    selected: list[str] = []
    for keywords, items in SCENE_NEGATIVE_RULES:
        if has_any_keyword(context, keywords):
            selected.extend(items)
    return selected


def unique_items(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = re.sub(r"\s+", "", item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(item)
    return result
