# -*- coding: utf-8 -*-
import sys
import datetime
import akshare as ak
import pandas as pd


def get_target_trade_date():
    now = datetime.datetime.now()
    today_str = now.strftime('%Y%m%d')
    today_str_f = now.strftime('%Y-%m-%d')
    
    # 获取所有交易日历
    try:
        trade_dates = ak.tool_trade_date_hist_sina()
        # trade_dates 是 DataFrame，包含 'trade_date' 列，类型可能是 datetime.date
        trade_dates_list = trade_dates['trade_date'].astype(str).tolist()
    except Exception as e:
        print(f"获取交易日历失败: {e}")
        # 兜底：简单按工作日处理
        return _fallback_target_date(now)
    
    # 判断今天是否交易日
    if today_str_f in trade_dates_list:
        # 是交易日，判断时间是否 >= 18:00
        if now.hour >= 18:
            return today_str
        else:
            # 未到18点，取上一个交易日
            pass
    # 不是交易日，或未到18点，取上一个交易日
    # 从交易日列表中筛选小于今天的最大日期
    prev_dates = [d for d in trade_dates_list if d < today_str_f]
    if prev_dates:
        return max(prev_dates).replace('-','')
    else:
        # 没有更早的交易日，返回今天（极端情况）
        return today_str

def _fallback_target_date(now):
    """兜底逻辑：按周一至周五判断，下午18点后取今天，否则取上一个工作日"""
    today = now.date()
    # 如果今天是周一至周五且时间 >= 18:00
    if today.weekday() < 5 and now.hour >= 18:
        return today.strftime('%Y%m%d')
    # 否则往前找上一个工作日
    delta = 1
    while True:
        prev = today - datetime.timedelta(days=delta)
        if prev.weekday() < 5:
            return prev.strftime('%Y%m%d')
        delta += 1


def get_volume(target_date=None):
    """
    收盘后获取指定交易日的沪深两市成交额。
    数据来源：上交所/深交所官方市场总貌接口（方法二）。

    :param target_date: 交易日，格式 'YYYYMMDD'，默认取今日。
    :return: 含 volume（亿元）的字典；获取失败返回 None。
    """
    if target_date is None:
        target_date = get_target_trade_date()

    # ---------- 1. 上交所成交额（单位：亿元） ----------
    sse_volume = 0.0
    try:
        df_sse = ak.stock_sse_deal_daily(date=target_date)
        # 返回的 DataFrame 中，'单日情况' 列包含 '成交金额' 行
        sse_row = df_sse[df_sse['单日情况'] == '成交金额']
        if not sse_row.empty:
            # '股票' 列即为上交所全部股票成交金额，单位已是亿元
            sse_volume = float(sse_row['股票'].values[0])
            print(f"上交所成交额: {sse_volume:.2f} 亿元")
        else:
            print("警告: 上交所返回数据中未找到'成交金额'行")
    except Exception as e:
        print(f"上交所成交额获取失败: {e}")

    # ---------- 2. 深交所成交额（原始单位：元，需转换为亿元） ----------
    szse_volume = 0.0
    try:
        df_szse = ak.stock_szse_summary(date=target_date)
        # 筛选 '证券类别' 为 '股票' 的行，取 '成交金额' 列
        szse_row = df_szse[df_szse['证券类别'] == '股票']
        if not szse_row.empty:
            szse_amount_yuan = float(szse_row['成交金额'].values[0])
            szse_volume = szse_amount_yuan / 1e8  # 元 -> 亿元
            print(f"深交所成交额: {szse_volume:.2f} 亿元")
        else:
            print("警告: 深交所返回数据中未找到'股票'类别")
    except Exception as e:
        print(f"深交所成交额获取失败: {e}")

    # ---------- 3. 汇总与输出 ----------
    return sse_volume + szse_volume


def get_market_emotion(target_date=None):
    print(f"开始获取当前交易日短线情绪数据...")
    """
    收盘后获取某天盘面数据。
    target_date: 'YYYYMMDD'，None 则取最近交易日
    """
    if target_date is None:
        target_date = get_target_trade_date()

    # 涨停池——一次拿到所有涨停股票（含连板天数、涨停原因等）
    try:
        df_zt = ak.stock_zt_pool_em(date=target_date)
        limit_up_count = len(df_zt)
    except Exception as e:
        print(f"涨停池获取失败: {e}")
        limit_up_count = 0

    # 跌停池——一次拿到所有跌停股票
    try:
        df_dt = ak.stock_zt_pool_dtgc_em(date=target_date)
        limit_down_count = len(df_dt)
    except Exception as e:
        print(f"跌停池获取失败: {e}")
        limit_down_count = 0

    # 炸板池——曾涨停但收盘未封住
    try:
        df_zb = ak.stock_zt_pool_zbgc_em(date=target_date)
        zhaban_count = len(df_zb)
    except Exception as e:
        print(f"炸板池获取失败: {e}")
        zhaban_count = 0

    # 4. 获取今日市场总成交额 (单位：亿元)
    total_volume_billion = get_volume(target_date)

    
    # 5. 计算日内大面股 (最高价到最低价回撤超过 12% 且最终收盘不佳)
    # 回撤幅度 = (最高价 - 最低价) / 昨收
    # df_clean['amplitude_drop'] = (df_clean['最高'] - df_clean['最低']) / (df_clean['最新价'] - df_clean['涨跌额']) * 100
    # big_face_count = len(df_clean[(df_clean['amplitude_drop'] >= 12) & (df_clean['涨跌幅'] < 2)])

    print(f"\n========= 短线情绪核心看板 =========")
    print(f"交易日期: {target_date}")
    print(f"涨停家数: {limit_up_count} 家")
    print(f"跌停家数: {limit_down_count} 家")
    print(f"炸板家数: {zhaban_count} 家")
    print(f"炸板率: {zhaban_count / (limit_up_count + zhaban_count) * 100:.1f}%")
    print(f"两市总成交额: {total_volume_billion:.2f} 亿元")
    print("=====================================\n")

    return {
        "volume": total_volume_billion,
        "limit_up": limit_up_count,
        "limit_down": limit_down_count,
        "zhaban": zhaban_count,
        "big_face": 0
    }



def judge_market_stage(emotion_data):
    """
    根据可量化的短线指标，智能判定市场情绪周期与赚钱效应
    :param emotion_data: 包含 volume, limit_up, limit_down, big_face 的字典
    :return: 判定结果字典
    """
    v = emotion_data["volume"]
    lu = emotion_data["limit_up"]
    ld = emotion_data["limit_down"]
    bf = emotion_data["big_face"]

    # 初始化各周期的得分倾向
    scores = {
        "破冰/启动期": 0,
        "主升/发酵期": 0,
        "高位分歧期": 0,
        "退潮/冰点期": 0
    }

    # ----------------------------------------------------
    # 核心量化打分矩阵
    # ----------------------------------------------------

    # 1. 依据涨停家数打分
    if lu > 70:
        scores["主升/发酵期"] += 3
        scores["高位分歧期"] += 1
    elif 45 <= lu <= 70:
        scores["高位分歧期"] += 2
        scores["破冰/启动期"] += 1
    elif 25 <= lu < 45:
        scores["破冰/启动期"] += 2
        scores["退潮/冰点期"] += 1
    else:
        scores["退潮/冰点期"] += 4  # 涨停极少，极大概率是冰点

    # 2. 依据跌停家数打分 (一票否决权极高)
    if ld <= 2:
        scores["主升/发酵期"] += 3
        scores["破冰/启动期"] += 2
    elif 3 <= ld <= 7:
        scores["高位分歧期"] += 3
        scores["破冰/启动期"] += 1
    elif 8 <= ld <= 15:
        scores["高位分歧期"] += 1
        scores["退潮/冰点期"] += 2
    else:
        scores["退潮/冰点期"] += 5  # 跌停大爆发，绝对的退潮/冰点

    # 3. 依据日内大面股打分 (衡量短线追高风险)
    if bf == 0:
        scores["主升/发酵期"] += 2
        scores["破冰/启动期"] += 1
    elif 1 <= bf <= 4:
        scores["主升/发酵期"] += 1
        scores["高位分歧期"] += 2
    elif 5 <= bf <= 10:
        scores["高位分歧期"] += 3
        scores["退潮/冰点期"] += 1
    else:
        scores["退潮/冰点期"] += 3  # 面条满天飞，市场进入亏钱退潮

    # ----------------------------------------------------
    # 综合判定逻辑
    # ----------------------------------------------------
    # 找出得分最高的周期阶段
    final_stage = max(scores, key=scores.get)

    # 衍生判定：日内赚钱效应 (Profit_Effect)
    if final_stage == "主升/发酵期":
        profit_effect = "极佳/高潮"
        action_advice = "重仓接力，坚定拥抱核心龙头，容错率极高。"
        suggested_position = "70% - 100% (满仓猛干)"
    elif final_stage == "破冰/启动期":
        profit_effect = "常态/回暖"
        action_advice = "积极试错新题材首板或一进二，分批建仓破局高标。"
        suggested_position = "30% - 50% (轻仓试错)"
    elif final_stage == "高位分歧期":
        profit_effect = "撕裂/风险预警"
        action_advice = "去弱留强，严禁碰中位股和跟风小弟，资金开始向唯一高标抱团。"
        suggested_position = "20% - 40% (聚焦防守)"
    else:  # 退潮/冰点期
        profit_effect = "极差/全面亏钱"
        action_advice = "高位股连续A杀，管住手，空仓或仅一成仓位博弈极少数老妖股的冰点反抽。"
        suggested_position = "0% - 10% (严格管手)"

    # 结合量能的修正建议
    if v < 6000 and final_stage in ["主升/发酵期", "高位分歧期"]:
        action_advice += " (警告：两市量能不足6000亿，属于存量深度抱团，后排跟风极其容易冲高回落！)"
        if suggested_position == "70% - 100% (满仓猛干)":
            suggested_position = "50% 左右 (因量能不足压制仓位)"

    return {
        "market_stage": final_stage,
        "profit_effect": profit_effect,
        "suggested_position": suggested_position,
        "action_advice": action_advice
    }

# ----------------------------------------------------
# 模拟运行测试
# ----------------------------------------------------
def _test():
    # 模拟一个真实的“高位分歧期”数据
    mock_data_1 = {
        "volume": 7800,       # 7800亿温和放量
        "limit_up": 55,       # 涨停55家（常态）
        "limit_down": 6,      # 跌停6家（开始亏钱）
        "big_face": 7         # 大面股7家（追高开始面人）
    }

    # 模拟一个极端的“全面退潮冰点期”数据
    mock_data_2 = {
        "volume": 5500,       # 5500亿绝对缩量
        "limit_up": 18,       # 涨停仅18家
        "limit_down": 28,      # 跌停高达28家（大面积核按钮）
        "big_face": 12        # 大面股12家
    }

    print("测试场景 1：")
    result_1 = judge_market_stage(mock_data_1)
    print(f"判定周期阶段: {result_1['market_stage']}")
    print(f"日内赚钱效应: {result_1['profit_effect']}")
    print(f"交易大师建议: {result_1['action_advice']}")
    print(f"推荐仓位上限: {result_1['suggested_position']}")

    print("\n" + "="*50 + "\n")

    print("测试场景 2：")
    result_2 = judge_market_stage(mock_data_2)
    print(f"判定周期阶段: {result_2['market_stage']}")
    print(f"日内赚钱效应: {result_2['profit_effect']}")
    print(f"交易大师建议: {result_2['action_advice']}")
    print(f"推荐仓位上限: {result_2['suggested_position']}")

if __name__ == "__main__":
    # _test()
    # sys.exit() 

    emotion_data = get_market_emotion()
    if not emotion_data:
        emotion_data = {}
        print('数据获取失败')
        sys.exit(1) 
    result = judge_market_stage(emotion_data)
    print(f"判定周期阶段: {result['market_stage']}")
    print(f"日内赚钱效应: {result['profit_effect']}")
    print(f"交易大师建议: {result['action_advice']}")
    print(f"推荐仓位上限: {result['suggested_position']}")
