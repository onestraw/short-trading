# -*- coding: utf-8 -*-
"""增强版复盘数据采集（带限流与本地缓存，适配低积分 token）。"""
import os
import sys
import json
import time
import pandas as pd
import tushare as ts
from datetime import datetime, timedelta

ts.set_token(os.environ['TUSHARE_TOKEN'])
pro = ts.pro_api()

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.cache')
os.makedirs(CACHE_DIR, exist_ok=True)


def call(name, fn, *args, **kwargs):
    """限流 + 重试 + 本地缓存。"""
    key = f"{name}_{'_'.join(str(a) for a in args)}_{'_'.join(f'{k}={v}' for k, v in sorted(kwargs.items()))}"
    path = os.path.join(CACHE_DIR, key.replace('/', '_') + '.pkl')
    if os.path.exists(path):
        return pd.read_pickle(path)
    for attempt in range(5):
        try:
            df = fn(*args, **kwargs)
            df.to_pickle(path)
            return df
        except Exception as e:
            msg = str(e)
            if '超限' in msg or 'IP' in msg or '频率' in msg or '每分钟' in msg:
                time.sleep(25)
                continue
            raise
    raise RuntimeError(f'{name} 多次重试仍被限流')


def main(target_date=None):
    end = target_date or datetime.now().strftime('%Y%m%d')
    start = (datetime.strptime(end, '%Y%m%d') - timedelta(days=45)).strftime('%Y%m%d')
    cal = call('trade_cal', pro.trade_cal, exchange='SSE', start_date=start, end_date=end)
    open_days = cal[cal.is_open == 1]['cal_date'].sort_values(ascending=True).tolist()

    if target_date:
        eligible = [d for d in open_days if d <= target_date]
        assert eligible, '目标日期之前无有效交易日'
        trade_date = eligible[-1]
    else:
        trade_date = None
        for d in reversed(open_days):
            idx = call('index_daily', pro.index_daily, ts_code='000001.SH', start_date=d, end_date=d)
            if not idx.empty:
                trade_date = d
                break
    assert trade_date, '未找到有效交易日'

    idx_pos = open_days.index(trade_date)
    recent_days = open_days[max(0, idx_pos - 5):idx_pos + 1]  # 最近6个交易日

    # ---- 大盘 ----
    hist = call('index_daily', pro.index_daily, ts_code='000001.SH',
                start_date=(datetime.strptime(trade_date, '%Y%m%d') - timedelta(days=70)).strftime('%Y%m%d'),
                end_date=trade_date).sort_values('trade_date')
    close = float(hist.iloc[-1]['close'])
    pct = float(hist.iloc[-1]['pct_chg'])
    ma5 = float(hist['close'].tail(5).mean())
    ma20 = float(hist['close'].tail(20).mean())
    amount = float(hist.iloc[-1]['amount']) / 100000.0  # 千元 -> 亿元
    vol = float(hist.iloc[-1]['vol'])
    vol_ma5 = float(hist['vol'].tail(5).mean())
    try:
        idx_basic = call('index_dailybasic', pro.index_dailybasic, trade_date=trade_date, ts_code='000001.SH')
        turn = float(idx_basic.iloc[0]['turnover_rate'])
        pe = float(idx_basic.iloc[0]['pe'])
    except Exception:
        turn = pe = None

    # ---- 股票基础 ----
    sb = call('stock_basic', pro.stock_basic, exchange='', list_status='L',
              fields='ts_code,name,industry,market')
    sb['is_st'] = sb['name'].str.contains('ST', na=False)

    # ---- 逐日 daily + stk_limit ----
    frames = {}
    for d in recent_days:
        dl = call('daily', pro.daily, trade_date=d)
        lim = call('stk_limit', pro.stk_limit, trade_date=d)
        m = dl.merge(lim[['ts_code', 'up_limit', 'down_limit']], on='ts_code', how='left')
        m = m.merge(sb, on='ts_code', how='left')
        m['up'] = (m['close'] >= m['up_limit'] - 0.001).astype(int)
        m['down'] = (m['close'] <= m['down_limit'] + 0.001).astype(int)
        m['zha'] = ((m['high'] >= m['up_limit'] - 0.001) & (m['close'] < m['up_limit'] - 0.001)).astype(int)
        frames[d] = m

    today = frames[trade_date]
    up_stocks = today[today['up'] == 1]
    down_stocks = today[today['down'] == 1]
    zha_stocks = today[today['zha'] == 1]

    advance = int((today['pct_chg'] > 0).sum())
    decline = int((today['pct_chg'] < 0).sum())
    flat = int((today['pct_chg'] == 0).sum())
    limit_up = len(up_stocks)
    limit_down = len(down_stocks)
    zhadan = len(zha_stocks)
    seal_rate = round(limit_up / (limit_up + zhadan) * 100, 2) if (limit_up + zhadan) > 0 else 0.0

    # ---- 连板数 ----
    all_codes = sorted(set().union(*[set(frames[d]['ts_code']) for d in recent_days]))
    up_status = pd.DataFrame(index=all_codes)
    for d in recent_days:
        up_status[d] = frames[d].set_index('ts_code')['up'].reindex(all_codes).fillna(0).astype(int)

    def consec_run(row):
        c = 0
        for d in reversed(recent_days):
            if row[d] == 1:
                c += 1
            else:
                break
        return c

    today['limit_times'] = up_status.reindex(today['ts_code']).fillna(0).apply(consec_run, axis=1).values
    leader_df = today[today['limit_times'] >= 1].sort_values('limit_times', ascending=False)
    two_ban = int((today['limit_times'] >= 2).sum())
    three_ban = int((today['limit_times'] >= 3).sum())

    # ---- 溢价 ----
    zt_yj = lb_yj = None
    if len(recent_days) >= 2:
        y = recent_days[-2]
        yesterday_up = frames[y][frames[y]['up'] == 1]['ts_code'].tolist()
        y_up_today = today[today['ts_code'].isin(yesterday_up)]
        if len(y_up_today):
            zt_yj = round(float(y_up_today['pct_chg'].mean()), 2)
        if len(recent_days) >= 3:
            y2 = recent_days[-3]
            y2_up = frames[y2][frames[y2]['up'] == 1]['ts_code'].tolist()
            yesterday_2ban = frames[y][(frames[y]['up'] == 1) & (frames[y]['ts_code'].isin(y2_up))]['ts_code'].tolist()
            y2_today = today[today['ts_code'].isin(yesterday_2ban)]
            lb_yj = round(float(y2_today['pct_chg'].mean()), 2) if len(y2_today) else None

    # ---- 主力资金 ----
    mf = call('moneyflow', pro.moneyflow, trade_date=trade_date)
    mf = mf.merge(sb[['ts_code', 'industry', 'name']], on='ts_code', how='left')
    mf['main_net'] = (mf['buy_lg_amount'] - mf['sell_lg_amount']) + (mf['buy_elg_amount'] - mf['sell_elg_amount'])
    total_main = float(mf['main_net'].sum()) / 10000.0
    ind_flow = mf.groupby('industry')['main_net'].sum().sort_values(ascending=False)
    flow_in = ind_flow.head(5)
    flow_out = ind_flow.tail(5).iloc[::-1]

    # ---- 北向 ----
    try:
        hsgt = call('moneyflow_hsgt', pro.moneyflow_hsgt, trade_date=trade_date)
        north = float(hsgt.iloc[0]['north_money']) / 10000.0 if not hsgt.empty else None
    except Exception:
        north = None

    # ---- 板块涨停排行（按行业近似）----
    up_industry = up_stocks.groupby('industry').size().sort_values(ascending=False)

    # ---- 行业涨幅 ----
    ind_pct = today.groupby('industry')['pct_chg'].agg(['mean', 'count']).sort_values('mean', ascending=False)

    result = {
        'trade_date': trade_date,
        'recent_days': recent_days,
        'index': {
            'close': round(close, 2), 'pct': round(pct, 2),
            'ma5': round(ma5, 2), 'ma20': round(ma20, 2),
            'amount_yi': round(amount, 2), 'vol_ratio': round(vol / vol_ma5, 2) if vol_ma5 else None,
            'turnover_rate': turn, 'pe': round(pe, 2) if pe else None,
        },
        'market': {
            'advance': advance, 'decline': decline, 'flat': flat,
            'limit_up': limit_up, 'limit_down': limit_down, 'zhadan': zhadan,
            'seal_rate': seal_rate, 'two_ban': two_ban, 'three_ban': three_ban,
            'zt_yj': zt_yj, 'lb_yj': lb_yj,
        },
        'leader': leader_df[['ts_code', 'name', 'industry', 'market', 'limit_times', 'pct_chg']].head(10).to_dict('records'),
        'up_industry_top': up_industry.head(10).to_dict(),
        'fund_flow': {
            'total_main_yi': round(total_main, 2),
            'in': [{'industry': k, 'net_yi': round(float(v) / 10000.0, 2)} for k, v in flow_in.items()],
            'out': [{'industry': k, 'net_yi': round(float(v) / 10000.0, 2)} for k, v in flow_out.items()],
            'north_yi': round(north, 2) if north is not None else None,
        },
        'ind_pct_top': ind_pct.head(10).reset_index().rename(columns={'industry': 'name', 'mean': 'pct', 'count': 'n'}).to_dict('records'),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else None
    main(target)
