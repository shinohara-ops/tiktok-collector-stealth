"""Live / Music / Game / Pet / Food / general NG カテゴリ別キーワード判定。

6 カテゴリを順番にチェック。各カテゴリは:
  - モジュール内の hardcoded ワードリスト
  - rules.{category}_keywords(yaml or Sheets 経由)
の合算に対して _contains_any で部分一致をチェックする。

  1. 配信/LIVE/ライバー(19 語)→ 「配信/LIVE系({hit})」
  2. 音楽/外部映像/アイドル(150+ 語、=LOVE / 乃木坂46 / 櫻坂46 / 日向坂46 /
     AKB48 / TWICE / BLACKPINK / NewJeans 等)→ 「音楽/外部映像系({hit})」
  3. ゲーム(13 語)→ 「ゲーム系({hit})」
  4. 動物/ペット(20 語)→ 「動物/ペット系({hit})」
  5. 食べ物(20 語)→ 「食べ物/料理系({hit})」
  6. その他 NG(50+ 語)→ 「NGワード({hit})」
"""
from __future__ import annotations


from ._helpers import _contains_any, _load_extra_words


_LIVE_WORDS: list[str] = [
    "配信中", "配信者", "配信垢", "配信アカウント", "ライブ配信", "live配信",
    "tiktok live", "tiktoklive", "ライバー", "17ライブ", "pococha", "ポコチャ",
    "showroom", "ふわっち", "ツイキャス", "ミクチャ", "palmu", "iriam",
    "グループ配信",
]

_MUSIC_WORDS: list[str] = [
    "歌詞動画", "歌詞", "lyrics", "lyric", "lyric video", "弾き語り", "歌ってみた",
    "cover", "カバー", "mv", "pv", "music video", "作曲", "編曲", "同時再生",
    "比較してみた", "切り抜き", "文字起こし", "転載", "拾い画", "拾い動画",
    "外部映像", "ライブ映像", "live映像", "ステージ", "マイク", "ピンマイク",
    "アーティスト", "推し", "映画", "ドラマ", "アニメ", "漫画",
    "大森元貴", "大森元気", "mrs. green apple", "ミセス", "sekai no owari",
    "セカオワ", "嵐", "love so sweet", "babymonster", "初音ミク", "名探偵コナン",
    "kiminitodoke", "君に届け", "naruto", "anime", "contentcreator",
    "最終未来少女", "地下アイドル", "アイドルグループ", "女優", "俳優", "芸能人",
    "芸能", "タレント", "舞台", "出演", "ファンアカウント",
    "blackpink",
    "マカロニえんぴつ",
    "akumanoko",
    "attackontitan", "shingekinokyojin", "進撃の巨人",
    "idol glow", "idolglo", "berry表記",
    "洋楽", "洋楽和訳", "洋楽紹介", "洋楽おすすめ", "和訳動画",
    "水曜日のダウンタウン", "浜田雅功", "松本人志",
    "aiko", "kisshug", "キスハグ",
    "=LOVE", "イコラブ",
    "佐々木舞香", "大谷映美里", "大場花菜", "音嶋莉沙", "齋藤樹愛羅",
    "髙松瞳", "高松瞳", "瀧脇笙古", "野口衣織", "諸橋沙夏", "山本杏奈",
    "≠ME", "ノイミー",
    "尾木波菜", "落合希来里", "蟹沢萌子", "河口夏音", "川中子奈月心",
    "櫻井もも", "菅波美玲", "鈴木瞳美", "谷崎早耶", "冨田菜々風",
    "永田詩央里", "本田珠由記",
    "≒JOY", "ニアジョイ",
    "逢田珠里依", "天野香乃愛", "市原愛弓", "江角怜音", "大信田美月",
    "大西葵", "小澤愛実", "高橋舞", "藤沢莉子", "村山結香",
    "山田杏佳", "山野愛月",
    "乃木坂46", "乃木坂", "櫻坂46", "櫻坂", "日向坂46", "日向坂",
    "井上和", "遠藤さくら", "賀喜遥香", "筒井あやめ", "久保史緒里",
    "梅澤美波", "与田祐希", "山下美月", "齋藤飛鳥", "白石麻衣",
    "西野七瀬", "生田絵梨花",
    "森田ひかる", "山﨑天", "山崎天", "田村保乃", "藤吉夏鈴",
    "守屋麗奈", "小林由依", "渡邉理佐", "菅井友香",
    "小坂菜緒", "金村美玖", "河田陽菜", "丹生明里", "齊藤京子",
    "加藤史帆", "佐々木美玲",
    "AKB48", "AKB", "小栗有以", "倉野尾成美", "村山彩希", "柏木由紀", "本田仁美",
    "NMB48", "HKT48", "SKE48", "STU48", "NGT48",
    "FRUITS ZIPPER", "ふるっぱー",
    "櫻井優衣", "鎮西寿々歌", "松本かれん", "月足天音",
    "仲川瑠夏", "真中まな", "早瀬ノエル",
    "高嶺のなでしこ", "たかねこ", "松本ももな", "橋本桃呼",
    "ME:I", "ミーアイ",
    "笠原桃奈", "村上璃杏", "櫻井美羽", "石井蘭", "山本すず",
    "NiziU", "ニジュー",
    "TWICE", "BLACKPINK",
    "IVE", "NewJeans", "LE SSERAFIM", "ILLIT",
]

_GAME_WORDS: list[str] = [
    "ゲーム", "ゲーム実況", "apex", "荒野行動", "原神", "ポケモン", "スプラトゥーン",
    "プロセカ", "フォートナイト", "minecraft", "マイクラ", "valorant", "モンスト",
]

_PET_WORDS: list[str] = [
    "猫", "ねこ", "ネコ", "猫のいる生活", "猫好きさんと繋がりたい", "三毛猫", "保護猫",
    "犬", "いぬ", "イヌ", "dog", "cat", "ハムスター", "うさぎ", "bunnies", "ペット", "動物",
    "ハリネズミ", "はりねずみ", "hedgehog",
    "柴犬", "しばいぬ", "shibainu", "shiba inu",
]

_FOOD_WORDS: list[str] = [
    "ラーメン", "カレー", "グルメ", "飯テロ", "食べ歩き", "自炊", "レシピ",
    "スイーツ", "ランチ", "ディナー", "居酒屋", "焼肉", "寿司",
    "沖縄そば", "飲食店", "レストラン", "食堂", "日本美食", "美食",
    "そば", "うどん", "定食",
    "カフェ巡り", "カフェ紹介", "カフェメニュー", "カフェランチ", "カフェ飯",
]

_GENERAL_WORDS: list[str] = [
    "お●2", "もっと載せてる", "dm", "独身", "婚活", "恋活", "副業勧誘", "投資",
    "fx", "仮想通貨", "稼げる", "稼ぎ方", "情報商材",
    "マスク", "顔隠し", "顔出しなし", "顔なし", "雰囲気だけ",
    "2ch", "5ch", "shorts",
    "ネット系",
    "合成", "モザイク", "ピクセル", "サングラス",
    "キャラクター", "アバター", "外部メディア", "キャラクターイラスト",
    "ハローキティ", "キティ",
    "スタンプで隠れ", "顔スタンプ",
    "番組切り抜き", "テレビ切り抜き",
    "真剣", "友達作り",
    "にほん", "日本",
    "相互フォロー", "フォロバ", "フォロー返し", "相互垢", "フォロバ100",
]


def check(text: str, rules) -> str | None:
    hit = _contains_any(text, _LIVE_WORDS + _load_extra_words(rules, "live_keywords"))
    if hit:
        return "配信/LIVE系(" + hit + ")"

    hit = _contains_any(text, _MUSIC_WORDS + _load_extra_words(rules, "music_keywords"))
    if hit:
        return "音楽/外部映像系(" + hit + ")"

    hit = _contains_any(text, _GAME_WORDS + _load_extra_words(rules, "game_keywords"))
    if hit:
        return "ゲーム系(" + hit + ")"

    hit = _contains_any(text, _PET_WORDS + _load_extra_words(rules, "pet_keywords"))
    if hit:
        return "動物/ペット系(" + hit + ")"

    hit = _contains_any(text, _FOOD_WORDS + _load_extra_words(rules, "food_keywords"))
    if hit:
        return "食べ物/料理系(" + hit + ")"

    hit = _contains_any(text, _GENERAL_WORDS + _load_extra_words(rules, "ng_keywords"))
    if hit:
        return "NGワード(" + hit + ")"

    return None
