# -*- coding: utf-8 -*-
"""概念板块数据采集（成交量TOP5 + 涨停股数量TOP5），基于东财 + curl_cffi 浏览器指纹。"""
import json
import os
import sys
import time
from curl_cffi import requests as cr

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.cache', 'concept_data.json')
IMP = 'chrome124'
HDR = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://quote.eastmoney.com/',
}

# 排除「指数/风格/地域/特殊」类板块，仅保留主题型概念板块
BLOCK = (
    '融资融券', '深股通', '沪股通', '富时罗素', 'MSCI', '标准普尔', '深成', '上证', '中证', '创业板综',
    '创业成份', '深证', '大盘', '小盘', '中盘', '百元股', '高市净率', '高市盈率', '机构重仓', '基金重仓',
    'QFII', '权重股', '行业龙头', '央国企', '专精特新', '预增', '预盈', '绩优', '白马股', 'AH股', 'AB股',
    'HS300', '次新', '破净', '低价股', '高价股', '中字头', '微盘股', '题材股', '趋势股', '昨日连板',
    '昨日涨停', '昨日高振幅', '最近多板', '东方财富热股', '近期新高', '百日新高', '昨日炸板', '昨日触板',
    '市场热门', '人气', '广东板块', '深圳特区', '西部大开发', '长江三角', '京津冀', '长三角', '珠三角',
    '大湾区', '上海本地', '北京板块', '江苏板块', '浙江板块', '山东板块', '福建板块', '河南板块',
    '湖北板块', '湖南板块', '四川板块', '重庆板块', '陕西板块', '辽宁板块', '安徽板块', '河北板块',
    '山西板块', '吉林板块', '黑龙江板块', '江西板块', '云南板块', '贵州板块', '广西板块', '海南板块',
    '甘肃板块', '青海板块', '宁夏板块', '新疆板块', '西藏板块', '内蒙古板块', '天津板块', '贵州',
)


def is_thematic(name):
    if not name:
        return False
    return not any(k in name for k in BLOCK)


def get(url, params, tries=6):
    for i in range(tries):
        try:
            r = cr.get(url, params=params, headers=HDR, impersonate=IMP, timeout=20)
            return r.json()
        except Exception:
            time.sleep(3 * (i + 1))
    raise RuntimeError('请求失败: %s' % url)


def fetch_concept_boards():
    url = 'https://push2.eastmoney.com/api/qt/clist/get'
    boards = []
    pn = 1
    while True:
        params = {'pn': str(pn), 'pz': '100', 'po': '1', 'np': '1', 'fltt': '2', 'invt': '2',
                  'fid': 'f6', 'fs': 'm:90+t:3', 'fields': 'f12,f14,f3,f6'}
        j = get(url, params)
        d = j.get('data') or {}
        total = d.get('total', 0)
        diff = d.get('diff') or {}
        rows = list(diff.values()) if isinstance(diff, dict) else diff
        for row in rows:
            code = (row.get('f12') or '').replace('BK', '')
            try:
                code_int = int(code)
            except ValueError:
                continue
            boards.append({'code': code_int, 'name': row.get('f14'), 'pct': row.get('f3'), 'amount': row.get('f6')})
        if pn * 100 >= total or not rows:
            break
        pn += 1
        time.sleep(0.8)
    return boards


def fetch_zt_pool(date):
    url = 'https://push2ex.eastmoney.com/getTopicZTPool'
    params = {'ut': '7eea3edcaed734bea9cbfc24409ed989', 'dpt': 'wz.ztzt',
              'Pageindex': '0', 'pagesize': '10000', 'sort': 'fbt:asc', 'date': date}
    j = get(url, params)
    pool = (j.get('data') or {}).get('pool') or []
    out = []
    for p in pool:
        out.append({'code': p.get('c'), 'name': p.get('n'), 'industry': p.get('hybk')})
    return out


def fetch_stock_boards(code):
    if code.startswith(('6', '9')):
        secid = 'SH' + code
    elif code.startswith(('4', '8')):
        secid = 'BJ' + code
    else:
        secid = 'SZ' + code
    url = 'https://emweb.securities.eastmoney.com/PC_HSF10/CoreConception/PageAjax'
    j = get(url, {'code': secid})
    out = []
    for b in (j.get('ssbk') or []):
        out.append({'code': b.get('BOARD_CODE'), 'name': b.get('BOARD_NAME'),
                    'precise': b.get('IS_PRECISE')})
    return out


def main(date='20260824'):
    if os.path.exists(CACHE):
        print(json.dumps(json.load(open(CACHE)), ensure_ascii=False, indent=2))
        return

    boards = fetch_concept_boards()
    code2board = {b['code']: b for b in boards}
    zt = fetch_zt_pool(date)

    cnt = {}
    detail = {}
    for s in zt:
        try:
            bs = fetch_stock_boards(s['code'])
        except Exception:
            bs = []
        concepts = []
        for b in bs:
            # 优先用“精确概念”标记，且板块名在主题型概念集合内
            try:
                bc = int(b['code'])
            except (TypeError, ValueError):
                continue
            board = code2board.get(bc)
            if not board or not is_thematic(board['name']):
                continue
            concepts.append(board['name'])
        detail[s['code']] = {'name': s['name'], 'industry': s['industry'], 'concepts': concepts}
        for c in concepts:
            cnt[c] = cnt.get(c, 0) + 1
        time.sleep(0.4)

    # 成交量 TOP（主题型概念，按成交额降序，单位亿元）
    thematic = [b for b in boards if is_thematic(b['name'])]
    amount_top = sorted(thematic, key=lambda x: -(x['amount'] or 0))[:8]
    amount_top = [{'name': b['name'], 'amount_yi': round((b['amount'] or 0) / 1e8, 2), 'pct': b['pct']}
                  for b in amount_top]

    # 涨停数量 TOP
    top_cnt = sorted(cnt.items(), key=lambda x: -x[1])[:8]
    top_cnt = [{'name': k, 'limit_up': v} for k, v in top_cnt]

    result = {'date': date, 'concept_total': len(boards), 'thematic_total': len(thematic),
              'zt_total': len(zt), 'amount_top': amount_top, 'limit_up_top': top_cnt,
              'zt_detail': detail}
    json.dump(result, open(CACHE, 'w'), ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '20260824')
