"""数据预处理: 合并两个抓取来源, 整理出建模用的最终数据集。

输入(都在 data/ 下, 由爬虫产出):
  A) 爬虫/che168_wuhan_brands.csv         按品牌页抓的 30 个品牌; 品牌名来自 URL, 权威
  B) 数据处理/che168_wuhan_cars.raw.csv   早先混合品牌抓的列表页(31 列)

流程:
  1. A + B 合并(按车源ID去重, A 优先); B 的品牌名用 A 得到的 brandid->品牌名 映射补
  2. 丢掉「品牌名称」或「车龄(年)」为空的行
  3. 补 车系名称 / 年均里程, 并丢掉里程矛盾行
  4. 过滤: 品牌样本数 >= MIN_BRAND 且 车系样本数 >= MIN_SERIES(反复过滤到稳定)
  5. 补三个目标编码特征: 品牌折价率 / 车系折价率 / 车系中位价
     ⚠️ 必须在第 4 步【之后】算, 否则被过滤掉的行仍会影响中位数
  6. 写 data/che168_wuhan_cars.csv, 并把 品牌/车系 查表导出成 app/reference.json

两个数据版本(靠 --v1 区分):
  默认    v2: 做车系名称规范化 + 分组过滤, 训练和应用都用它
  --v1    v1: 不做规范化和分组过滤, 写 che168_wuhan_cars_v1.csv 且不碰 reference.json
              (这是"第一版可用数据", 用来体现版本演进, 差异见 ml/README_data.md)
"""
import csv
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
V1 = "--v1" in sys.argv  # 控制产出 v1 还是 v2
CSV = DATA_DIR / ("che168_wuhan_cars_v1.csv" if V1 else "che168_wuhan_cars.csv")
BRAND_SRC = DATA_DIR / "爬虫" / "che168_wuhan_brands.csv"
OLD_SRC = DATA_DIR / "数据处理" / "che168_wuhan_cars.raw.csv"
REFERENCE_FILE = DATA_DIR.parent / "app" / "reference.json"

TARGET = "售价(万元)"                # 预测目标
GUIDE = "新车指导价(万元)"            # 算折价率要用

MIN_BRAND = 5                       # 品牌至少这么多条样本才保留: 样本太少时它的折价率就是它自己
MIN_SERIES = 3                      # 车系同上
MAX_MILEAGE_PER_YEAR = 10.0         # 年均里程超过这个值判定为录错(相当于每天 274 公里全年无休)
REQUIRED = ["品牌名称", "车龄(年)"]   # 这两列为空的行不可靠, 整行丢掉

# 最终数据集保留的列, 顺序即输出顺序
KEEP_COLUMNS = [
    "车源ID", "详情页", "车型", "品牌名称", "车系名称",
    "品牌ID", "车系ID",
    "售价(万元)", "新车指导价(万元)",
    "品牌平均折价率(%)", "车系平均折价率(%)", "车系历史中位价(万元)",
    "表显里程(万公里)", "车龄(年)", "年均里程(万公里/年)",
    "0次过户", "原厂质保", "发布时间", "准新车标记(站点)", "封面图",
]


def _num(text):
    """字符串转 float, 转不动就返回 None(而不是抛异常)。"""
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _round2(text):
    value = _num(text)
    return None if value is None else round(value, 2)


def read_table(path: Path):
    """读一张表, 返回 (列名, 数据行)。文件前两行是标题行, 第 3 行才是列名。"""
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    return rows[2], rows[3:]


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
brand_col, brand_rows = read_table(BRAND_SRC)
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
merged: list[list] = [
    [dict(zip(brand_col, row, strict=False)).get(k) for k in KEEP_COLUMNS]
    for row in brand_rows
]
seen_ids = {row[brand_col.index("车源ID")] for row in brand_rows}

print(f"来源 B(混合品牌): {OLD_SRC.name}")
old_col, old_rows = read_table(OLD_SRC)
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
        bid2name.get(src.get("品牌ID")),  # 只有 A 覆盖到的品牌才有名字
        None,                            # 车系名称, 第 3 步统一补
        src.get("品牌ID"),
        src.get("车系ID"),
        src.get(TARGET),
        src.get(GUIDE),
        None,                            # 品牌平均折价率, 第 5 步统一算
        None,                            # 车系平均折价率, 第 5 步统一算
        None,                            # 车系历史中位价, 第 5 步统一算
        src.get("表显里程(万公里)"),
        src.get("车龄(年)"),
        None,                            # 年均里程, 第 3 步统一补
        1 if "0次过户" in tags else 0,
        1 if "原厂质保" in tags else 0,
        src.get("发布时间"),
        src.get("准新车标记(站点)"),
        src.get("封面图"),
    ])
    added += 1
print(f"  补入 {added} 条(A 里没有的), 合并后 {len(merged)} 条")

name_to_idx = {n: i for i, n in enumerate(KEEP_COLUMNS)}

# ---------------------------------------------------------------- 2) 丢掉不确定的行
for name in REQUIRED:
    idx = name_to_idx[name]
    before = len(merged)
    merged = [r for r in merged if r[idx] not in (None, "")]
    print(f"丢掉「{name}」为空的: -{before - len(merged)} 条, 剩 {len(merged)} 条")

# ---------------------------------------------------------------- 3) 补派生列
# 车系名称: 原始数据里有一列, 但早期抓的那批没有, 从车型名里切出来
series_name_idx = name_to_idx["车系名称"]
filled = 0
for row in merged:
    if not row[series_name_idx]:
        row[series_name_idx] = _series_name_of(row[name_to_idx["车型"]])
        filled += 1
if filled:
    print(f"已补出「车系名称」{filled} 条")

# 车系名称规范化: 同一个车系ID 只保留出现最多的那种写法。
# 同一个车系会有 "揽胜极光进口" / "揽胜极光(进口)" 这类变体, 不规范化的话
# 车系ID 和 车系名称 就不是一一对应, 应用的下拉框会出现同一个车系的两个选项。
# v1 不做这一步 —— 这是 v1 与 v2 的差异之一。
series_idx = name_to_idx["车系ID"]
if V1:
    print("v1: 跳过车系名称规范化")
else:
    spellings = defaultdict(Counter)
    for row in merged:
        if row[series_name_idx]:
            spellings[row[series_idx]][row[series_name_idx]] += 1
    canonical = {sid: c.most_common(1)[0][0] for sid, c in spellings.items()}
    fixed = 0
    for row in merged:
        if row[series_name_idx]:
            best = canonical.get(row[series_idx], row[series_name_idx])
            fixed += best != row[series_name_idx]
            row[series_name_idx] = best
    kinds = len({r[series_name_idx] for r in merged if r[series_name_idx]})
    print(f"车系名称规范化: {len(canonical)} 个车系ID 各取最常见写法, 修正 {fixed} 条, 剩 {kinds} 种")

# 站点标记统一成 0/1 (爬虫早期版本写的是 是/否, 已抓下来的数据要就地转换)
flag_idx = name_to_idx["准新车标记(站点)"]
converted = 0
for row in merged:
    if row[flag_idx] in ("是", "否"):
        row[flag_idx] = 1 if row[flag_idx] == "是" else 0
        converted += 1
if converted:
    print(f"「准新车标记(站点)」是/否 -> 1/0: 转换 {converted} 条")

# 年均里程: 里程 / 车龄(车龄为 0 时没有意义, 填 0)
per_idx = name_to_idx["年均里程(万公里/年)"]
for row in merged:
    mileage = _num(row[name_to_idx["表显里程(万公里)"]])
    age = _num(row[name_to_idx["车龄(年)"]])
    row[per_idx] = round(mileage / age, 2) if (mileage is not None and age) else 0

# 丢掉自相矛盾的行(车龄很短却里程很高)
before = len(merged)
merged = [r for r in merged if (_num(r[per_idx]) or 0) <= MAX_MILEAGE_PER_YEAR]
print(f"丢掉「年均里程 > {MAX_MILEAGE_PER_YEAR} 万/年」的矛盾行: "
      f"-{before - len(merged)} 条, 剩 {len(merged)} 条")

# ---------------------------------------------------------------- 4) 过滤到稳定
# v1 不做这一步 —— 这是 v1 与 v2 的第二个差异(也是 v1 行数更多的原因)。
if V1:
    print("v1: 跳过分组过滤(保留所有品牌/车系, 含样本量很少的组)")
else:
    before = len(merged)
    while True:
        size = len(merged)
        for key, least in (("品牌ID", MIN_BRAND), ("车系ID", MIN_SERIES)):
            idx = name_to_idx[key]
            counts = Counter(r[idx] for r in merged)
            merged = [r for r in merged if counts[r[idx]] >= least]
        if len(merged) == size:
            break  # 这一轮没删掉任何东西 → 稳定了
    print(f"分组过滤: -{before - len(merged)} 条 "
          f"({(before - len(merged)) / before * 100:.1f}%), 剩 {len(merged)} 条")

# ---------------------------------------------------------------- 5) 目标编码特征
# ⚠️ 这三列必须放在「组过滤」【之后】算。
#
# 它们都是拿售价算出来的(售价就是预测目标, 所以叫目标编码):
#     品牌/车系折价率 = 该组每行 (新车指导价 - 售价) / 新车指导价 的中位数
#     车系中位价      = 该车系每行售价的中位数
#
# 如果在过滤之前算, 被删掉的那些行仍然会参与中位数, 结果就是
# CSV / app/reference.json 里存的值 ≠ 训练时用过滤后数据重算的值,
# 等于训练和应用喂给模型的特征分布不完全一样(train/serve skew)。
discounts = []
for row in merged:
    price = _num(row[name_to_idx[TARGET]])
    guide = _num(row[name_to_idx[GUIDE]])
    discounts.append((guide - price) / guide * 100 if (price and guide) else None)

for key, out in (("品牌ID", "品牌平均折价率(%)"), ("车系ID", "车系平均折价率(%)")):
    key_idx = name_to_idx[key]
    bucket = defaultdict(list)
    for row, value in zip(merged, discounts, strict=True):
        if row[key_idx] and value is not None:
            bucket[row[key_idx]].append(value)
    medians = {k: round(statistics.median(v), 2) for k, v in bucket.items()}
    for row in merged:
        row[name_to_idx[out]] = medians.get(row[key_idx])
    print(f"已补出「{out}」({len(medians)} 个组)")

price_idx = name_to_idx[TARGET]
mid_idx = name_to_idx["车系历史中位价(万元)"]
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


def write_reference(rows: list[list]) -> None:
    """导出 品牌/车系 -> ID + 查表特征, 给应用做名称查表(app/reference.json)。"""
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


# ---------------------------------------------------------------- 6) 输出
# CSV 是 3 行表头: 标题行 + 维度行 + 真正的列名行(train.py 用 header=2 读)
title_row = [f"车源数据(按维度整理) 来源 {BRAND_SRC.name} + {OLD_SRC.name} 共 {len(merged)} 条"]
dim_row = ["标识", "标识", "车辆", "车辆", "车辆", "车辆", "车辆",
           "价格", "价格", "价格", "价格", "价格",
           "车况", "车况", "车况", "车况", "车况",
           "交易", "交易", "媒体"]
with CSV.open("w", encoding="utf-8-sig", newline="") as fh:
    writer = csv.writer(fh)
    writer.writerow(title_row)
    writer.writerow(dim_row)
    writer.writerow(KEEP_COLUMNS)
    writer.writerows(merged)

print(f"\n已写回 {CSV.name}: {len(merged)} 条, {len(KEEP_COLUMNS)} 列")

# 数据集变了, 应用那份对照表必须跟着更新, 否则表单里选不到新品牌/新车系。
# v1 是历史版本, 不覆盖应用正在用的对照表。
if V1:
    print("v1: 不更新 app/reference.json(那是 v2 的产物)")
else:
    write_reference(merged)
