#!/usr/bin/env python3
"""Verify the isolated local demo API; never creates an order or payment."""
import json
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler
from urllib.parse import urlencode
opener=build_opener(ProxyHandler({}))
base="http://127.0.0.1:48080/app-api"
ids=[880000000401,880000000402,880000000403]
checks=[]
def get(label,path,params,validate):
    url=base+path+("?"+urlencode(params) if params else "")
    try:
        with opener.open(Request(url,headers={"tenant-id":"1","terminal":"10"}),timeout=15) as response:
            body=json.load(response)
        assert body.get("code")==0, str(body.get("msg"))
        assert validate(body.get("data")), "Unexpected demo data"
        checks.append({"name":label,"passed":True})
    except Exception as error:
        checks.append({"name":label,"passed":False,"error":str(error)[:250]})
get("enabled DIY template","/promotion/diy-template/used",{},lambda d:bool(d and d.get("home") and d.get("user")))
get("product categories","/product/category/list",{},lambda d:len(d)>=2)
get("product list","/product/spu/page",{"pageNo":1,"pageSize":10},lambda d:set(map(str,ids)).issubset({str(x["id"]) for x in d["list"]}))
for product_id in ids:
    get("product detail "+str(product_id),"/product/spu/get-detail",{"id":product_id},lambda d:d and d.get("skus") and d["skus"][0]["stock"]==100)
get("settlement product prices","/trade/order/settlement-product",{"spuIds":",".join(map(str,ids))},lambda d:isinstance(d,list) and len(d)==3)
result={"allPassed":all(x["passed"] for x in checks),"checks":checks,"scope":"Public APIs with original backend code and clearly labeled local demo data; no real login/payment/fulfillment verified."}
Path(__file__).with_name("verification-result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False,indent=2))
raise SystemExit(0 if result["allPassed"] else 1)
