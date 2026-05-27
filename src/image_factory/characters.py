"""Canonical character aliases and group member lists.

This is the single source of truth. Modules that need character-name
resolution or group-membership lookup should import from here.
"""

CHARACTER_ALIASES: dict[str, str] = {
    "灯": "高松灯",
    "Tomori": "高松灯",
    "Tomori Takamatsu": "高松灯",
    "爱音": "千早爱音",
    "愛音": "千早爱音",
    "Anon": "千早爱音",
    "Anno": "千早爱音",
    "Anon Chihaya": "千早爱音",
    "乐奈": "要乐奈",
    "楽奈": "要乐奈",
    "Raana": "要乐奈",
    "Rana": "要乐奈",
    "Kaname Raana": "要乐奈",
    "素世": "长崎素世",
    "爽世": "长崎素世",
    "Soyo": "长崎素世",
    "立希": "椎名立希",
    "Taki": "椎名立希",
    "睦": "若叶睦",
    "Mutsumi": "若叶睦",
    "Mutsumi Wakaba": "若叶睦",
    "祥子": "丰川祥子",
    "Sakiko": "丰川祥子",
    "初华": "三角初华",
    "初華": "三角初华",
    "Uika": "三角初华",
}

GROUP_CHARACTER_NAMES: dict[str, list[str]] = {
    "MyGO": ["高松灯", "千早爱音", "要乐奈", "长崎素世", "椎名立希"],
    "MyGO!!!!!": ["高松灯", "千早爱音", "要乐奈", "长崎素世", "椎名立希"],
    "CRYCHIC": ["高松灯", "丰川祥子", "若叶睦", "长崎素世", "椎名立希"],
    "Ave Mujica": ["丰川祥子", "若叶睦", "三角初华"],
}

GROUP_TOKENS: frozenset[str] = frozenset(GROUP_CHARACTER_NAMES.keys())
