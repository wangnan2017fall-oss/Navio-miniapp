#!/usr/bin/env python3
"""Create original, visibly marked local demo data. No real goods or credentials."""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FRONTEND = ROOT.parent / "yudao-mall-uniapp"
BASE = 880000000000
IDS = {
    "categoryRoot": BASE + 100, "category": BASE + 101, "brand": BASE + 200,
    "property": BASE + 300, "propertyValue": BASE + 301,
    "spus": [BASE + 401, BASE + 402, BASE + 403],
    "skus": [BASE + 501, BASE + 502, BASE + 503],
    "template": BASE + 600, "home": BASE + 601, "user": BASE + 602,
    "tradeConfig": BASE + 700, "memberConfig": BASE + 701,
    "deliveryTemplate": BASE + 800, "deliveryCharge": BASE + 801,
    "deliveryFree": BASE + 802,
}


class Raw(str):
    pass


def literal(value):
    if isinstance(value, Raw):
        return value
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "b'1'" if value else "b'0'"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, dict)):
        value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def component(kind, **values):
    values.setdefault("style", {
        "bgType": "color", "bgColor": "#ffffff", "marginLeft": 12,
        "marginRight": 12, "marginBottom": 12, "paddingLeft": 12,
        "paddingRight": 12, "paddingTop": 8, "paddingBottom": 8,
        "borderTopLeftRadius": 12, "borderTopRightRadius": 12,
        "borderBottomLeftRadius": 12, "borderBottomRightRadius": 12,
    })
    return {"id": kind, "property": values}


def navbar(title):
    cell = {"type": "text", "width": 6, "height": 1, "top": 0, "left": 0,
            "text": title, "textColor": "#111111", "borderRadius": 0,
            "url": "/pages/index/index"}
    return {"bgType": "color", "bgColor": "#ffffff", "bgImg": "",
            "styleType": "normal", "showType": "always", "alwaysShow": True,
            "mpCells": [cell], "otherCells": [{**cell, "width": 8}]}


def build_data(asset_base):
    img = lambda name: asset_base + "/" + name + ".png"
    tab_items = [
        ("首页", "/pages/index/index", "home"),
        ("分类", "/pages/index/category", "category"),
        ("购物车", "/pages/index/cart", "cart"),
        ("我的", "/pages/index/user", "mine"),
    ]
    template = {"tabBar": {
        "theme": "blue", "mode": 1,
        "style": {"bgType": "color", "bgColor": "#ffffff", "bgImg": "",
                  "color": "#8a9099", "activeColor": "#4285ff"},
        "items": [{"text": text, "url": url, "iconUrl": img(icon),
                   "activeIconUrl": img(icon + "-active")} for text, url, icon in tab_items],
    }}
    notice = lambda text: component("NoticeBar", iconUrl=img("notice"), textColor="#536579",
                                     contents=[{"text": text, "url": "/pages/goods/list"}])
    home = {
        "page": {"backgroundColor": "#f2f3f5", "backgroundImage": ""},
        "navigationBar": navbar("本地演示商城"),
        "components": [
            notice("本地演示：商品、价格与库存均为测试值；不提供真实交易。"),
            component("SearchBar", placeholder="搜索本地演示样品", borderRadius=20,
                      hotKeywords=[], textColor="#4285ff"),
            component("TitleBar", title="本地演示 · 基础流程", titleSize=22,
                      titleColor="#111111", titleWeight="bold", textAlign="left",
                      description="原创测试商品，不对应供应商货盘或真实报价。",
                      descriptionColor="#7d8590", descriptionSize=11,
                      descriptionWeight="normal", height=70, bgImgUrl="", marginLeft=0,
                      more={"show": True, "type": "text", "text": "全部", "url": "/pages/goods/list"}),
            component("ProductCard", layoutType="twoCol", spuIds=IDS["spus"],
                      fields={"name": {"show": True, "color": "#111111"},
                              "introduction": {"show": True, "color": "#7d8590"},
                              "price": {"show": True, "color": "#4285ff"},
                              "marketPrice": {"show": False, "color": "#aaaaaa"},
                              "salesCount": {"show": False, "color": "#aaaaaa"},
                              "stock": {"show": True, "color": "#aaaaaa"}},
                      badge={"show": False, "imgUrl": ""},
                      btnBuy={"type": "text", "text": "查看样品", "bgBeginColor": "#4285ff",
                              "bgEndColor": "#4285ff", "imgUrl": ""},
                      borderRadiusTop=12, borderRadiusBottom=12, space=8),
        ],
    }
    user = {
        "page": {"backgroundColor": "#f2f3f5", "backgroundImage": ""},
        "navigationBar": navbar("本地演示 · 我的"),
        "components": [
            notice("此页面仅验证本地会员与订单入口，不连接真实支付或物流。"),
            component("UserCard", space=0),
            component("UserOrder", space=0),
            component("MenuList", list=[
                {"title": text, "titleColor": "#222222", "subtitle": "本地演示入口",
                 "subtitleColor": "#8a9099", "url": url, "iconUrl": ""}
                for text, url in [("我的订单", "/pages/order/list"),
                                  ("我的优惠券", "/pages/coupon/list"),
                                  ("收货地址", "/pages/user/address/list"),
                                  ("账户资料", "/pages/user/info")]
            ]),
        ],
    }
    rows = []

    def add(table, **data):
        rows.append((table, {**data, "tenant_id": 1, "creator": "local-demo",
                             "updater": "local-demo", "deleted": False}))

    add("product_category", id=IDS["categoryRoot"], parent_id=0, name="本地演示（非真实货盘）",
        pic_url=img("category"), sort=0, status=0)
    add("product_category", id=IDS["category"], parent_id=IDS["categoryRoot"], name="本地演示样品",
        pic_url=img("category"), sort=0, status=0)
    add("product_brand", id=IDS["brand"], name="LOCAL DEMO 本地演示", pic_url=img("brand"),
        sort=0, description="原创开发占位品牌，不是供应商或真实保健品品牌。", status=0)
    add("product_property", id=IDS["property"], name="演示规格", remark="本地演示属性")
    add("product_property_value", id=IDS["propertyValue"], property_id=IDS["property"],
        name="演示装·非卖品", remark="本地演示属性值")
    sku_properties = [{"propertyId": IDS["property"], "propertyName": "演示规格",
                       "valueId": IDS["propertyValue"], "valueName": "演示装·非卖品"}]
    for i, label in enumerate("ABC"):
        price = (i + 1) * 100
        picture = img("product-" + label.lower())
        add("product_spu", id=IDS["spus"][i], name=f"本地演示样品 {label}（非卖品）",
            keyword=f"本地演示 样品 {label}", introduction="仅用于开发验证；价格与库存均为测试值。",
            description="<h3>本地演示，非真实商品</h3><p>本条记录用于商品展示、规格、购物车和结算流程的本机验证。</p><p>没有供应商、产地、成分、疗效或真实销售承诺；不用于真实交易。</p>",
            category_id=IDS["category"], brand_id=IDS["brand"], pic_url=picture,
            slider_pic_urls=[picture], sort=3-i, status=1, spec_type=True, price=price,
            market_price=price, cost_price=0, stock=100, delivery_types="1",
            delivery_template_id=IDS["deliveryTemplate"], give_integral=0,
            sub_commission_type=False, sales_count=0, virtual_sales_count=0, browse_count=0)
        add("product_sku", id=IDS["skus"][i], spu_id=IDS["spus"][i], properties=sku_properties,
            price=price, market_price=price, cost_price=0, bar_code=f"LOCAL-DEMO-{label}",
            pic_url=picture, stock=100, weight=0.1, volume=0.001,
            first_brokerage_price=0, second_brokerage_price=0, sales_count=0)
    add("trade_delivery_express_template", id=IDS["deliveryTemplate"], name="本地演示·零运费",
        charge_mode=1, sort=0)
    add("trade_delivery_express_template_charge", id=IDS["deliveryCharge"],
        template_id=IDS["deliveryTemplate"], area_ids="1", charge_mode=1,
        start_count=1.0, start_price=0, extra_count=1.0, extra_price=0)
    add("trade_delivery_express_template_free", id=IDS["deliveryFree"],
        template_id=IDS["deliveryTemplate"], area_ids="1", free_price=0, free_count=0)
    add("trade_config", id=IDS["tradeConfig"], after_sale_refund_reasons=["本地演示退款原因"],
        after_sale_return_reasons=["本地演示退货原因"], delivery_express_free_enabled=True,
        delivery_express_free_price=0, delivery_pick_up_enabled=False, brokerage_enabled=False,
        brokerage_enabled_condition=1, brokerage_bind_mode=1, brokerage_poster_urls=[],
        brokerage_first_percent=0, brokerage_second_percent=0, brokerage_withdraw_min_price=0,
        brokerage_withdraw_fee_percent=0, brokerage_frozen_days=0, brokerage_withdraw_types="")
    add("member_config", id=IDS["memberConfig"], point_trade_deduct_enable=False,
        point_trade_deduct_unit_price=1, point_trade_deduct_max_price=0, point_trade_give_point=0)
    add("promotion_diy_template", id=IDS["template"], name="本地演示·原创基础模板",
        used=Raw("@local_demo_can_activate"), used_time=Raw("CURRENT_TIMESTAMP(6)"),
        remark="本地原创测试模板；不来自受限附件或外部演示数据库。",
        preview_pic_urls="", property=template)
    add("promotion_diy_page", id=IDS["home"], template_id=IDS["template"], name="首页",
        remark="本地原创开发页面", preview_pic_urls="", property=home)
    add("promotion_diy_page", id=IDS["user"], template_id=IDS["template"], name="我的",
        remark="本地原创开发页面", preview_pic_urls="", property=user)
    return rows, (template, home, user)


def validate(rows, documents):
    spec = importlib.util.spec_from_file_location("local_schema_generator", HERE / "generate_schema.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    schema = {t["table"]: set(t["columns"]) | {"tenant_id"} for t in module.generate(check_only=True)["tables"]}
    for table, row in rows:
        unknown = set(row) - schema[table]
        if unknown:
            raise ValueError(f"Unknown columns for {table}: {unknown}")
    app = json.loads((FRONTEND / "unpackage/dist/dev/mp-weixin/app.json").read_text())
    routes = {"/" + p for p in app["pages"]}
    for sub in app.get("subPackages", []):
        routes.update("/" + sub["root"] + "/" + p for p in sub["pages"])
    links = set()
    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "url" and child:
                    links.add(child.split("?", 1)[0])
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    for document in documents:
        walk(document)
    missing = links - routes
    if missing:
        raise ValueError(f"Unknown mini-program routes: {missing}")
    return {"seedRows": len(rows), "tables": sorted({t for t, _ in rows}),
            "verifiedRoutes": sorted(links), "unknownColumns": [], "unknownRoutes": []}


def generate_sql(rows):
    lines = [
        "-- LOCAL DEMO ONLY: original fictitious development data, not supplier goods or quotations.",
        "-- Apply only to the independent local test database AFTER generated-mall-schema.sql.",
        "-- All amounts are TEST integer fen; stock=100 is a TEST value; no real trade is verified.",
        "-- Fixed high IDs: 880000000000 + offsets. Re-running updates only these demo IDs.",
        "-- No member account, contact/address, order, coupon, SMS/social key, or payment channel is created.",
        "-- Existing used templates are not deactivated; this demo activates only if no other template is used.",
        "SET NAMES utf8mb4;", "START TRANSACTION;",
        f"SET @local_demo_can_activate := NOT EXISTS (SELECT 1 FROM `promotion_diy_template` WHERE `tenant_id`=1 AND `deleted`=b'0' AND `used`=b'1' AND `id`<>{IDS['template']});", "",
    ]
    for table, row in rows:
        cols = list(row)
        lines.append(f"-- Local demo {table}, ID {row['id']}")
        lines.append("INSERT INTO `" + table + "` (" + ",".join("`" + c + "`" for c in cols) + ")")
        lines.append("VALUES (" + ",".join(literal(row[c]) for c in cols) + ")")
        lines.append("ON DUPLICATE KEY UPDATE " + ",".join("`" + c + "`=VALUES(`" + c + "`)" for c in cols if c != "id") + ";\n")
    lines += ["COMMIT;", ""]
    (HERE / "local-demo-seed.sql").write_text("\n".join(lines))


def assets():
    from PIL import Image, ImageDraw, ImageFont
    target = HERE / "assets"
    target.mkdir(exist_ok=True)
    def draw_asset(name, product=None, active=False):
        size = 400 if product else 96
        image = Image.new("RGBA", (size, size), "white" if product else (255,255,255,0))
        draw = ImageDraw.Draw(image)
        color = "#4285ff" if active else "#8893a1"
        elements = []
        def line(points, fill, width=5):
            draw.line(points, fill=fill, width=width, joint="curve")
            elements.append('<polyline points="' + ' '.join(f'{x},{y}' for x,y in points) + f'" fill="none" stroke="{fill}" stroke-width="{width}" stroke-linejoin="round" stroke-linecap="round"/>')
        def rect(box, fill, radius=0, outline=None, width=1):
            draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)
            x,y,x2,y2=box
            elements.append(f'<rect x="{x}" y="{y}" width="{x2-x}" height="{y2-y}" rx="{radius}" fill="{fill or "none"}" stroke="{outline or "none"}" stroke-width="{width}"/>')
        def circle(box, fill, outline=None, width=1):
            draw.ellipse(box, fill=fill, outline=outline, width=width)
            x,y,x2,y2=box
            elements.append(f'<ellipse cx="{(x+x2)/2}" cy="{(y+y2)/2}" rx="{(x2-x)/2}" ry="{(y2-y)/2}" fill="{fill or "none"}" stroke="{outline or "none"}" stroke-width="{width}"/>')
        def text(x,y,value,fill,font_size):
            font=ImageFont.load_default(size=font_size)
            draw.text((x,y),value,fill=fill,font=font)
            elements.append(f'<text x="{x}" y="{y+font_size}" fill="{fill}" font-family="sans-serif" font-size="{font_size}">{escape(value)}</text>')
        if product:
            accent={"A":"#4285ff","B":"#7854b6","C":"#39a57f"}[product]
            rect((112,84,288,318),"#f3f5f8",24,outline="#d5dce5",width=3)
            rect((130,58,270,106),"#e5eaf0",8)
            rect((130,142,270,259),"#ffffff",6)
            rect((130,142,270,151),accent)
            text(142,167,"LOCAL",accent,28)
            text(142,205,"DEMO "+product,"#1f2b3b",26)
            text(120,341,"NOT FOR SALE",accent,22)
        elif name.startswith("home"):
            line([(15,43),(48,15),(81,43),(81,81),(15,81),(15,43)],color,6)
            line([(38,80),(38,59),(58,59),(58,80)],color,5)
        elif name.startswith("cart"):
            line([(11,19),(23,19),(34,65),(76,65),(86,33),(27,33)],color,6)
            circle((32,74,44,86),color);circle((66,74,78,86),color)
        elif name.startswith("mine"):
            circle((34,14,62,42),None,color,5)
            line([(17,81),(20,62),(34,51),(62,51),(76,62),(79,81)],color,5)
        elif name=="notice":
            line([(19,35),(37,35),(70,17),(70,79),(37,61),(19,61),(19,35)],color,5)
            line([(38,61),(43,82),(55,82),(51,67)],color,5)
        elif name=="brand":
            rect((8,8,88,88),"#4285ff",20)
            text(20,29,"DEMO","#ffffff",17)
            text(29,53,"ONLY","#ffffff",13)
        else:
            for x,y in [(16,16),(56,16),(16,56),(56,56)]:
                rect((x,y,x+24,y+24),None,5,color,4)
        image.save(target / (name + ".png"))
        (target / (name + ".svg")).write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}"><title>Original local development demo: {escape(name)}</title>' + ''.join(elements) + '</svg>')
    for label in "ABC":
        draw_asset("product-"+label.lower(), product=label)
    for name in ["brand", "notice", "category", "home", "cart", "mine"]:
        draw_asset(name)
    for name in ["category", "home", "cart", "mine"]:
        draw_asset(name+"-active", active=True)
    return sorted(p.name for p in target.glob("*.png"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-base", default="http://127.0.0.1:48081")
    args = parser.parse_args()
    if not re.fullmatch(r"http://(?:127\.0\.0\.1|localhost):\d+", args.asset_base):
        raise ValueError("Local demo assets must remain on a localhost HTTP service")
    rows, documents = build_data(args.asset_base)
    audit = validate(rows, documents)
    generate_sql(rows)
    audit["assets"] = assets()
    audit["ids"] = IDS
    print(json.dumps(audit, ensure_ascii=False, indent=2))
