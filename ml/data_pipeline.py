"""数据预处理(data pipeline): 合并两个抓取来源, 整理出建模用的最终数据集。

两个来源:
  A) 爬虫/che168_wuhan_brands.csv         按品牌页抓的 30 个品牌; 品牌名来自 URL, 权威
  B) 数据处理/che168_wuhan_cars.raw.csv   早先混合品牌抓的全量列表页(31 列)

流程:
  1. A + B 合并(按车源ID去重, A 优先); B 的品牌名由 A 得到的 brandid->品牌名 映射补
  2. 丢掉「品牌名称」或「车龄(年)」为空的行 —— 这部分不可靠
  3. 补 车系名称 / 年均里程 / 品牌车系平均折价率(缺才补)
  4. 过滤: 品牌样本数 >= MIN_BRAND 且 车系样本数 >= MIN_SERIES(反复过滤到稳定)
  5. 只输出 KEEP_COLUMNS -> che168_wuhan_cars.csv
  6. 顺手把 品牌/车系 -> ID + 查表特征 导出成 app/reference.json

应用(表单下拉 + 提交查表)读的就是第 6 步那份对照表, 所以数据变了这里一跑就同步。
"""
import csv
import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
CSV = HERE.parent / "data" / "che168_wuhan_cars.csv"
BRAND_SRC = HERE.parent / "data" / "爬虫" / "che168_wuhan_brands.csv"
OLD_SRC = HERE.parent / "data" / "数据处理" / "che168_wuhan_cars.raw.csv"
REFERENCE_FILE = HERE.parent / "app" / "reference.json"

# 品牌、车系至少要有这么多条样本才保留 —— 样本太少的组, 它的"平均折价率"就是它自己
MIN_BRAND = 5
MIN_SERIES = 3

# 最终数据集保留的列, 顺序即输出顺序
KEEP_COLUMNS = [
    "车源ID",
    "详情页",
    "车型",
    "品牌名称",
    "车系名称",
    "品牌ID",
    "车系ID",
    "售价(万元)",
    "新车指导价(万元)",
    "品牌平均折价率(%)",
    "车系平均折价率(%)",
    "车系历史中位价(万元)",
    "表显里程(万公里)",
    "车龄(年)",
    "年均里程(万公里/年)",
    "0次过户",
    "原厂质保",
    "发布时间",
    "准新车标记(站点)",
    "封面图",
]

# 参与建模的特征
FEATURES = [
    "品牌ID",
    "车系ID",
    "品牌平均折价率(%)",
    "车系平均折价率(%)",
    "车系历史中位价(万元)",
    "表显里程(万公里)",
    "车龄(年)",
    "年均里程(万公里/年)",
    "0次过户",
    "原厂质保",
    "发布时间",
    "准新车标记(站点)",
]

# 必须按「类别」处理、绝不能当数值算的列。
# 这些是网站自己的分类编号: 数字大小毫无意义(161 不比 160 "大"),
# 但同一个品牌/车系永远是同一个编号, 所以它是稳定的类别键, 不是随机数。
# 训练时必须开原生类别支持(LightGBM categorical_feature / CatBoost),
# 或改用 one-hot / 目标编码; 直接乘权重会得到无意义的结果。
CATEGORICAL = ["品牌ID", "车系ID"]

# 只作展示/标识, 不参与建模
DISPLAY_ONLY = [
    "车源ID",
    "详情页",
    "车型",
    "品牌名称",
    "车系名称",
    "新车指导价(万元)",
    "封面图",
]

TARGET = "售价(万元)"

# 丢掉这些字段为空的行: 品牌名是站点权威口径, 车龄是核心特征(年均里程也依赖它)
REQUIRED = ["品牌名称", "车龄(年)"]

# 年均里程超过这个值(万公里/年)判定为自相矛盾 —— 相当于每天 274 公里全年无休,
# 而它又是从"车龄很短 + 里程很高"算出来的, 通常是上牌时间或里程录错。
MAX_MILEAGE_PER_YEAR = 10.0


def _num(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def read_table(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    return rows[0], rows[1], rows[2], rows[3:]


def _series_name_of(title: str) -> str | None:
    """车型名 -> 车系名: 在第一个 "YYYY款" 处切开。按空格切会把 Model Y 截成 Model。"""
    if not title:
        return None
    m = re.match(r"^(.*?)\s+\d{4}款", title)
    name = m.group(1) if m else title.split(" ")[0]
    return name.strip() or None


def _tags_of(raw: str) -> set[str]:
    return {t for t in (raw or "").split("|") if t}


# ---------------------------------------------------------------- 1) 合并两个来源
print(f"来源 A(按品牌): {BRAND_SRC.name}")
_title, _dim, brand_col, brand_rows = read_table(BRAND_SRC)
print(f"  {len(brand_rows)} 条, {len(brand_col)} 列")

# A 顺带给出 brandid -> 品牌名 的权威映射
brand_id_col = brand_col.index("品牌ID")
brand_name_col = brand_col.index("品牌名称")
bid2name = {}
for row in brand_rows:
    if row[brand_id_col] and row[brand_name_col]:
        bid2name.setdefault(row[brand_id_col], row[brand_name_col])
print(f"  提供 {len(bid2name)} 个 brandid -> 品牌名")

# A 的行也要按列名投影到 KEEP_COLUMNS —— 它的列数和新版 KEEP_COLUMNS 未必一致,
# 直接 list(r) 会因为多一列/少一列而整体错位。
merged: list[list] = [[dict(zip(brand_col, r, strict=False)).get(k) for k in KEEP_COLUMNS]
                      for r in brand_rows]
seen_ids = {r[brand_col.index("车源ID")] for r in brand_rows}

print(f"来源 B(混合品牌): {OLD_SRC.name}")
_ot, _od, old_col, old_rows = read_table(OLD_SRC)
print(f"  {len(old_rows)} 条, {len(old_col)} 列")

added = 0
for row in old_rows:
    car_id = row[old_col.index("车源ID")]
    if car_id in seen_ids:
        continue
    seen_ids.add(car_id)
    src = dict(zip(old_col, row, strict=False))
    tags = _tags_of(src.get("车况标签"))
    merged.append([
        src.get("车源ID"),
        src.get("详情页"),
        src.get("车型"),
        bid2name.get(src.get("品牌ID")),          # 只有 A 覆盖到的品牌才有名字
        None,                                     # 车系名称, 后面统一补
        src.get("品牌ID"),
        src.get("车系ID"),
        src.get("售价(万元)"),
        src.get("新车指导价(万元)"),
        None,                                     # 品牌平均折价率, 后面统一补
        None,                                     # 车系平均折价率, 后面统一补
        None,                                     # 车系历史中位价, 后面统一补
        src.get("表显里程(万公里)"),
        src.get("车龄(年)"),
        None,                                     # 年均里程, 后面统一补
        1 if "0次过户" in tags else 0,
        1 if "原厂质保" in tags else 0,
        src.get("发布时间"),
        src.get("准新车标记(站点)"),
        src.get("封面图"),
    ])
    added += 1
print(f"  补入 {added} 条(A 里没有的)")
print(f"  合并后 {len(merged)} 条")

# ---------------------------------------------------------------- 2) 丢掉不确定的行
for name in REQUIRED:
    idx = KEEP_COLUMNS.index(name)
    before = len(merged)
    merged = [r for r in merged if r[idx] not in (None, "")]
    print(f"丢掉「{name}」为空的: -{before - len(merged)} 条, 剩 {len(merged)} 条")

# ---------------------------------------------------------------- 3) 补派生列
name_to_idx = {n: i for i, n in enumerate(KEEP_COLUMNS)}
missing_series = sum(1 for r in merged if not r[name_to_idx["车系名称"]])
if missing_series:
    for row in merged:
        if not row[name_to_idx["车系名称"]]:
            row[name_to_idx["车系名称"]] = _series_name_of(row[name_to_idx["车型"]])
    print(f"已补出「车系名称」({missing_series} 条), "
          f"共 {len({r[name_to_idx['车系名称']] for r in merged if r[name_to_idx['车系名称']]})} 种")

# 车系名称规范化: 同一个车系ID 只保留出现最多的那种写法
# (车型名是文本, 同一个车系会有 "揽胜极光进口" / "揽胜极光(进口)" 这类变体,
#  不规范化的话 车系ID <-> 车系名称 就不是一一对应, 用名字当类别特征会被拆碎)
series_idx = name_to_idx["车系ID"]
series_name_idx = name_to_idx["车系名称"]
spellings = defaultdict(Counter)
for row in merged:
    if row[series_name_idx]:
        spellings[row[series_idx]][row[series_name_idx]] += 1
canonical = {sid: c.most_common(1)[0][0] for sid, c in spellings.items()}
fixed = sum(1 for r in merged
            if r[series_name_idx] and canonical.get(r[series_idx]) != r[series_name_idx])
for row in merged:
    if row[series_name_idx]:
        row[series_name_idx] = canonical.get(row[series_idx], row[series_name_idx])
print(f"车系名称规范化: {len(canonical)} 个车系ID 各取最常见写法, 修正 {fixed} 条; "
      f"规范化后 {len({r[series_name_idx] for r in merged if r[series_name_idx]})} 种")

# 站点标记统一成 0/1 (爬虫早期版本写的是 是/否, 已抓下来的数据要就地转换)
flag_idx = name_to_idx["准新车标记(站点)"]
converted = 0
for row in merged:
    if row[flag_idx] in ("是", "否"):
        row[flag_idx] = 1 if row[flag_idx] == "是" else 0
        converted += 1
if converted:
    print(f"「准新车标记(站点)」是/否 -> 1/0: 转换 {converted} 条")

if any(not r[name_to_idx["年均里程(万公里/年)"]] for r in merged):
    filled0 = 0
    for row in merged:
        mileage = _num(row[name_to_idx["表显里程(万公里)"]])
        age = _num(row[name_to_idx["车龄(年)"]])
        per = round(mileage / age, 2) if (mileage is not None and age) else 0
        row[name_to_idx["年均里程(万公里/年)"]] = per
        filled0 += per == 0
    print(f"已补出「年均里程」(其中填 0 的 {filled0} 条)")

# 丢掉自相矛盾的行(车龄很短却里程很高)
per_year_idx = name_to_idx["年均里程(万公里/年)"]
before = len(merged)
merged = [r for r in merged if (_num(r[per_year_idx]) or 0) <= MAX_MILEAGE_PER_YEAR]
print(f"丢掉「年均里程 > {MAX_MILEAGE_PER_YEAR} 万/年」的矛盾行: "
      f"-{before - len(merged)} 条, 剩 {len(merged)} 条")

if any(not r[name_to_idx["品牌平均折价率(%)"]] for r in merged):
    discounts = []
    for row in merged:
        price = _num(row[name_to_idx["售价(万元)"]])
        guide = _num(row[name_to_idx["新车指导价(万元)"]])
        discounts.append((guide - price) / guide * 100 if (price and guide) else None)
    for key, out in (("品牌ID", "品牌平均折价率(%)"), ("车系ID", "车系平均折价率(%)")):
        key_idx = name_to_idx[key]
        bucket = defaultdict(list)
        for row, value in zip(merged, discounts):
            if row[key_idx] and value is not None:
                bucket[row[key_idx]].append(value)
        medians = {k: round(statistics.median(v), 2) for k, v in bucket.items()}
        out_idx = name_to_idx[out]
        for row in merged:
            row[out_idx] = medians.get(row[key_idx])
        print(f"已补出「{out}」({len(medians)} 个组)")

# 车系历史中位价: 该车系所有车源「售价」的中位数
# ⚠️ 这是直接用目标算出来的(目标编码)。数据集里存全量版供推理时查表;
#    训练评估必须在训练集上重算, 否则每行的特征里含自己那一行的售价, 指标会虚高。
mid_idx = name_to_idx["车系历史中位价(万元)"]
if any(not r[mid_idx] for r in merged):
    price_idx = name_to_idx["售价(万元)"]
    bucket = defaultdict(list)
    for row in merged:
        price = _num(row[price_idx])
        if row[series_idx] and price:
            bucket[row[series_idx]].append(price)
    medians = {k: round(statistics.median(v), 2) for k, v in bucket.items()}
    for row in merged:
        row[mid_idx] = medians.get(row[series_idx])
    print(f"已补出「车系历史中位价(万元)」({len(medians)} 个车系, "
          f"{min(medians.values()):.2f} ~ {max(medians.values()):.2f} 万)")

# ---------------------------------------------------------------- 4) 过滤到稳定
before = len(merged)
while True:
    size = len(merged)
    for key, least in (("品牌ID", MIN_BRAND), ("车系ID", MIN_SERIES)):
        idx = name_to_idx[key]
        counts = Counter(r[idx] for r in merged)
        merged = [r for r in merged if counts[r[idx]] >= least]
    if len(merged) == size:
        break
for key, least in (("品牌ID", MIN_BRAND), ("车系ID", MIN_SERIES)):
    counts = Counter(r[name_to_idx[key]] for r in merged)
    print(f"「{key}」>= {least}: 剩 {len(counts)} 组, 最少 {min(counts.values())} 条")
print(f"过滤共删除 {before - len(merged)} 条 ({(before - len(merged)) / before * 100:.1f}%)")

def _round2(text) -> float | None:
    value = _num(text)
    return None if value is None else round(value, 2)


def write_reference(rows: list[list]) -> None:
    """导出 品牌/车系 -> ID + 查表特征, 给应用做名称查表(app/reference.json)。

    ⚠️ 必须在样本数过滤之后调用 —— 样本太少的组, 中位价和折价率没有意义。
    """
    brands: dict[str, dict] = {}
    series: dict[str, dict] = {}
    for row in rows:
        brand = row[name_to_idx["品牌名称"]]
        series_name = row[name_to_idx["车系名称"]]
        if brand and brand not in brands:
            brands[brand] = {
                "id": row[name_to_idx["品牌ID"]],
                "discount_median": _round2(row[name_to_idx["品牌平均折价率(%)"]]),
            }
        if series_name and series_name not in series:
            series[series_name] = {
                "id": row[name_to_idx["车系ID"]],
                "brand": brand,
                "discount_median": _round2(row[name_to_idx["车系平均折价率(%)"]]),
                "price_median": _round2(row[name_to_idx["车系历史中位价(万元)"]]),
            }

    payload = {
        "_说明": f"由 ml/{Path(__file__).name} 生成, 请勿手改",
        "brands": dict(sorted(brands.items())),
        "series": dict(sorted(series.items())),
    }
    REFERENCE_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"已更新对照表 {REFERENCE_FILE.name}: {len(brands)} 个品牌, {len(series)} 个车系")


# ---------------------------------------------------------------- 5) 输出
title = [f"车源数据(按维度整理) 来源 {BRAND_SRC.name} + {OLD_SRC.name} 共 {len(merged)} 条"]
dim_row = ["标识", "标识", "车辆", "车辆", "车辆", "车辆", "车辆",
           "价格", "价格", "价格", "价格", "价格",
           "车况", "车况", "车况", "车况", "车况",
           "交易", "交易", "媒体"]
with CSV.open("w", encoding="utf-8-sig", newline="") as fh:
    writer = csv.writer(fh)
    writer.writerow(title)
    writer.writerow(dim_row)
    writer.writerow(KEEP_COLUMNS)
    writer.writerows(merged)

print()
print(f"已写回 {CSV.name}: {len(merged)} 条, {len(KEEP_COLUMNS)} 列")
print(f"特征 {len(FEATURES)} 个: {FEATURES}")
print(f"其中类别特征(必须按类别处理): {CATEGORICAL}")
print(f"只作展示 {len(DISPLAY_ONLY)} 个: {DISPLAY_ONLY}")
print(f"目标: {TARGET}")

# 数据集变了, 应用那份对照表必须跟着更新, 否则表单里选不到新品牌/新车系
write_reference(merged)
