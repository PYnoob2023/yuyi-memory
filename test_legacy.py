"""用模拟时钟和接近真实的对话样例验证记忆机制。运行: python test_memory.py

注意:这里的"整理器"是写死的假模型,所以测试证明的是代码层的校验、去重、回滚、衰减等逻辑,
不能证明真实模型提取得准不准。接真实 API 后,请抽查 episodes.json 和 mem.last_report。
"""
import json
import shutil
import tempfile
from pathlib import Path

from companion_memory import CompanionMemory, DAY, _conflicts, _same


class Clock:
    def __init__(self):
        self.t = 1_760_000_000.0

    def __call__(self):
        return self.t

    def advance(self, days):
        self.t += days * DAY


def new_mem(**cfg):
    d, clk = tempfile.mkdtemp(), Clock()
    return CompanionMemory(d, config=cfg, now_fn=clk), clk, d


def dlg(u1, a2="好的", u3="嗯", a4="嗯"):
    """4 条对话:1 用户 2 她 3 用户 4 她(整理至少需要 4 条)。"""
    return [("user", u1), ("assistant", a2), ("user", u3), ("assistant", a4)]


def run_batch(mem, clk, resp, turns, wait_days=1 / 24, capture=None):
    """加入对话,停顿后触发一次整理(假模型返回 resp)。返回本次统计。"""
    for role, text in turns:
        mem.add_turn(role, text)
    clk.advance(wait_days)

    def llm(prompt):
        if capture is not None:
            capture.append(prompt)
        return json.dumps(resp, ensure_ascii=False)

    assert mem.maybe_consolidate(llm) is True, mem.last_report
    return mem.last_report


def active_names(mem):
    return [n["name"] for n in mem.core["names"] if n["active"]]


# ------------------------------------------------------------------ 遗忘
def test_decay_timeline():
    mem, clk, d = new_mem()
    for imp in (3, 5, 8, 10):
        mem._add_event({"text": f"重要度{imp}的事件", "gist": f"概要{imp}", "impression": f"印象{imp}",
                        "importance": imp, "keywords": []})
    print("天数 | 重要度3 | 重要度5 | 重要度8 | 重要度10")
    last, result = 0, {}
    for day in (0, 2, 5, 15, 40, 100, 200, 400):
        clk.advance(day - last)
        last = day
        mem.decay()
        stages = {m["importance"]: m["stage"] for m in mem.episodes}
        row = [stages.get(i, "遗忘") for i in (3, 5, 8, 10)]
        result[day] = row
        print(f"{day:>4} | " + " | ".join(f"{s:<7}" for s in row))
    assert result[2] == ["vivid"] * 4
    assert result[5][0] == "faded" and result[5][1] == "vivid"
    assert result[15][0] == "遗忘"
    assert result[40][1] == "遗忘"
    assert result[100][2] == "faded"
    assert result[200][2] == "impression"
    assert result[400][2] == "遗忘"
    assert result[400][3] == "impression"
    m10 = [m for m in mem.episodes if m["importance"] == 10][0]
    assert m10["text"] is None and m10["gist"] is None and m10["impression"] == "印象10"
    shutil.rmtree(d)


def test_decay_runs_before_retrieval():
    """不手动调用 decay():只靠聊天时的 build_context,也会先遗忘再检索。"""
    mem, clk, d = new_mem()
    mem._add_event({"text": "一起去公园野餐", "gist": "公园野餐", "impression": "野餐",
                    "importance": 5, "keywords": ["野餐"]})
    clk.advance(15)
    ctx = mem.build_context("野餐")
    assert "一起去公园野餐" not in ctx and "公园野餐" in ctx
    assert mem.episodes[0]["stage"] == "faded" and mem.episodes[0]["text"] is None
    assert mem.episodes[0]["recall_count"] == 1
    clk.advance(100)
    mem.build_context("今天吃什么")
    assert mem.episodes == []
    shutil.rmtree(d)


def test_expired_items_are_not_revived_by_new_batch():
    """整理开始先衰减:超过 30 天的候选、已被遗忘的旧事件,不会被新一批"续命"。"""
    mem, clk, d = new_mem()
    mem._add_event({"text": "一起去公园野餐", "importance": 5, "keywords": []})
    cand = {"fact": "老李爱爬山", "explicit": False, "src": [1]}
    run_batch(mem, clk, {"core_candidates": [cand]}, dlg("我周末爱爬山"))
    assert mem.core["pending"][0]["count"] == 1
    clk.advance(40)
    run_batch(mem, clk, {"core_candidates": [cand],
                         "events": [{"text": "一起去公园野餐", "importance": 5, "src": [1]}]},
              dlg("我周末爱爬山,昨天还去公园野餐了"))
    assert mem.core["facts"] == []                                   # 没有因为"又出现一次"而晋升
    assert len(mem.core["pending"]) == 1 and mem.core["pending"][0]["count"] == 1
    assert len(mem.episodes) == 1 and mem.episodes[0]["recall_count"] == 0   # 是新事件,不是旧事件被巩固
    shutil.rmtree(d)


# ------------------------------------------------------------------ 整理触发与核心记忆
def test_consolidation_and_core():
    mem, clk, d = new_mem()
    calls = []

    def fake_llm(prompt):
        calls.append(prompt)
        return json.dumps({
            "events": [{"text": "老李今天换了新工作,有点紧张", "gist": "老李换工作", "impression": "老李换过工作",
                        "importance": 8, "keywords": ["工作", "紧张"], "src": [1]},
                       {"text": "随口聊了新工作的事", "importance": 1, "src": [1]}],
            "core_candidates": [{"fact": "老李在日本做物流机器人", "explicit": False, "src": [1]}]},
            ensure_ascii=False)

    first = "我今天换了新工作,有点紧张。我在日本做物流机器人"
    for i in range(19):  # 前 19 条不触发,第 20 条触发
        mem.add_turn("user" if i % 2 == 0 else "assistant", first if i == 0 else f"闲聊{i}")
        assert mem.maybe_consolidate(fake_llm) is False
    mem.add_turn("user", "闲聊19")
    assert mem.maybe_consolidate(fake_llm) is True and len(calls) == 1
    assert {k: mem.last_report[k] for k in ("invalid", "dropped_no_source", "dropped_ungrounded")} == \
        {"invalid": 0, "dropped_no_source": 0, "dropped_ungrounded": 0}
    assert len(mem.episodes) == 1                                    # 重要度1的闲话不入库
    assert mem.core["facts"] == [] and len(mem.core["pending"]) == 1

    mem.add_turn("user", "我今天换了新工作,有点紧张,我在日本做物流机器人")  # 第二次整理里再次出现
    for i in range(4):
        mem.add_turn("user", f"第二段{i}")
    clk.advance(1 / 24)
    assert mem.maybe_consolidate(fake_llm) is True and len(calls) == 2
    assert [f["fact"] for f in mem.core["facts"]] == ["老李在日本做物流机器人"]
    assert len(mem.episodes) == 1 and mem.episodes[0]["recall_count"] == 1

    for t in "xyzw":  # 整理失败不丢数据
        mem.add_turn("user", t)
    clk.advance(1 / 24)
    assert mem.maybe_consolidate(lambda p: "不是JSON") is False
    assert len(mem.state["pending"]) == 4 and "error" in mem.last_report

    mem2 = CompanionMemory(d, now_fn=clk)  # 重启后数据仍在
    assert len(mem2.episodes) == 1 and len(mem2.core["facts"]) == 1
    shutil.rmtree(d)


def test_batch_dedupe_makes_two_batches_real():
    """同一批里重复输出同一候选,只算一次:不会一次整理就晋升。"""
    mem, clk, d = new_mem()
    turns = dlg("我周末最爱爬山,爬山的时候心情特别好", "那我叫你山人好不好", "随便你", "山人今天也要加油")
    cand = {"fact": "老李爱爬山", "explicit": False, "src": [1]}
    nk = {"name": "山人", "explicit": False, "src": [2]}
    run_batch(mem, clk, {"core_candidates": [cand, dict(cand)], "nicknames": [nk, dict(nk)]}, turns)
    assert mem.core["facts"] == [] and mem.core["pending"][0]["count"] == 1
    assert active_names(mem) == [] and mem.core["names"][0]["count"] == 1
    run_batch(mem, clk, {"core_candidates": [cand], "nicknames": [nk]}, turns)
    assert [f["fact"] for f in mem.core["facts"]] == ["老李爱爬山"]
    assert active_names(mem) == ["山人"]
    shutil.rmtree(d)


def test_caps_never_evict_the_new_item():
    mem, clk, d = new_mem(names_max=2, core_max=2)
    explicit = [{"name": n, "explicit": True, "src": [1]} for n in ("甲", "乙", "丙")]
    run_batch(mem, clk, {"nicknames": explicit}, dlg("以后可以叫我甲,或者乙,或者丙"))
    assert len(active_names(mem)) == 2 and "丙" in active_names(mem)       # 最新的不会把自己挤掉
    ding = {"nicknames": [{"name": "丁", "explicit": False, "src": [2]}]}
    talk = dlg("今天天气不错", "丁先生,今天天气真好")
    run_batch(mem, clk, ding, talk)
    run_batch(mem, clk, ding, talk)
    assert len(active_names(mem)) == 2 and "丁" in active_names(mem)       # 重新激活的分支也受上限约束
    facts = [{"fact": f, "explicit": True, "src": [1]} for f in ("喜欢猫", "在东京工作", "周末爱爬山")]
    run_batch(mem, clk, {"core_candidates": facts}, dlg("我喜欢猫,在东京工作,周末爱爬山,请记住"))
    got = [f["fact"] for f in mem.core["facts"]]
    assert len(got) == 2 and "周末爱爬山" in got
    shutil.rmtree(d)


# ------------------------------------------------------------------ 纠错、删除、禁用
def test_revision_and_retraction():
    mem, clk, d = new_mem()
    prompts = []
    mem._add_event({"text": "老李每天早上都喝咖啡", "importance": 5, "keywords": []})
    run_batch(mem, clk, {"core_candidates": [{"fact": "喜欢喝咖啡", "explicit": True, "src": [1]}]},
              dlg("我最喜欢喝咖啡了,请记住"))
    assert _same("喜欢喝咖啡", "很喜欢喝咖啡") and not _same("喜欢喝咖啡", "不喜欢喝咖啡")
    assert _conflicts("喜欢喝咖啡", "不喜欢喝咖啡")

    # v2: 矛盾的说法进入待用户确认区，不再进入可自动晋升的候选。
    run_batch(mem, clk, {"core_candidates": [{"fact": "不喜欢喝咖啡", "explicit": False, "src": [1]}]},
              dlg("其实我有点不喜欢喝咖啡,太苦了"))
    assert mem.core["facts"][0]["count"] == 1 and len(mem.list_confirmations()) == 1

    # 改主意:替换。提示里带编号;矛盾的待观察候选被清理;旧事件被标注
    run_batch(mem, clk, {"core_updates": [{"index": 0, "new": "现在不喝咖啡了", "src": [1]}]},
              dlg("我现在不喝咖啡了,改喝茶"), capture=prompts)
    assert "[0] 喜欢喝咖啡" in prompts[0]
    assert [f["fact"] for f in mem.core["facts"]] == ["现在不喝咖啡了"]
    assert mem.core["pending"] == []
    assert mem.episodes[0].get("corrected") is True
    assert "当时如此,后来有变化" in mem.build_context("")

    # 她自己的话不能改写事实
    rep = run_batch(mem, clk, {"core_updates": [{"index": 0, "new": "其实爱喝茶", "src": [2]}]},
                    dlg("嗯", "其实你爱喝茶对吧"))
    assert [f["fact"] for f in mem.core["facts"]] == ["现在不喝咖啡了"] and rep["dropped_no_source"] == 1

    # 删除
    run_batch(mem, clk, {"core_updates": [{"index": 0, "new": None, "src": [3]}]},
              dlg("嗯", "嗯", "咖啡这条别记了", "好"))
    assert mem.core["facts"] == []
    shutil.rmtree(d)


def test_forget_clears_chat_so_it_cannot_return():
    mem, clk, d = new_mem()
    mem.remember("一起看了流星雨", importance=6)
    mem.add_turn("user", "我昨晚看了流星雨")
    assert mem.forget("流星") == 2                                   # 1 条事件 + 1 条聊天内容
    assert mem.state["recent"][-1]["text"] == "(这段内容已按要求删除)"
    assert mem.state["pending"][-1]["text"] == "(这段内容已按要求删除)"
    # 之后整理时,模型即使还想引用被删掉的那条发言,也对不上了
    rep = run_batch(mem, clk, {"events": [{"text": "老李昨晚看了流星雨", "importance": 7, "src": [1]}]},
                    [("assistant", "好看吗"), ("user", "嗯"), ("assistant", "嗯")])
    assert mem.episodes == [] and rep["dropped_ungrounded"] == 1
    # chat=False:只删长期记忆,不动聊天窗口
    mem.add_turn("user", "前天的流星雨")
    assert mem.forget("流星", chat=False) == 0 and mem.state["recent"][-1]["text"] == "前天的流星雨"
    shutil.rmtree(d)


def test_reject_name_persists():
    mem, clk, d = new_mem()
    assert mem.reject_name("李大人") is True
    mem2 = CompanionMemory(d, now_fn=clk)
    assert mem2.core["banned_names"] == ["李大人"]
    shutil.rmtree(d)


def test_nicknames():
    mem, clk, d = new_mem()
    assert mem.user_title == "老李"
    assert "称呼" in Path(d, "persona.md").read_text(encoding="utf-8")
    talk = dlg("以后你可以叫我小禾", "好呀李大人,小禾这个名字也不错,老李也行,我还能叫你超级超级超级长的称呼")
    run_batch(mem, clk, {"nicknames": [
        {"name": "李大人", "explicit": False, "src": [2]}, {"name": "小禾", "explicit": True, "src": [1]},
        {"name": "老李", "explicit": False, "src": [2]},
        {"name": "超级超级超级长的称呼", "explicit": False, "src": [2]}]}, talk)
    assert active_names(mem) == ["小禾"]                         # 明确要求立即记住;她自己起的先观察
    assert sorted(n["name"] for n in mem.core["names"]) == ["小禾", "李大人"]   # 默认称呼/过长的被忽略
    run_batch(mem, clk, {"nicknames": [{"name": "李大人", "explicit": False, "src": [2]}]},
              dlg("哈哈", "李大人今天辛苦啦"))
    assert set(active_names(mem)) == {"小禾", "李大人"}
    ctx = mem.build_context("")
    assert "默认叫“老李”" in ctx and "小禾" in ctx and "李大人" in ctx
    shutil.rmtree(d)


def test_banned_names():
    mem, clk, d = new_mem()
    run_batch(mem, clk, {"nicknames": [{"name": "李大人", "explicit": True, "src": [1]}]}, dlg("以后叫我李大人吧"))
    assert active_names(mem) == ["李大人"]
    rep = run_batch(mem, clk, {"rejected_nicknames": [{"name": "李大人", "src": [3]}]},
                    dlg("哈哈", "李大人好呀", "别叫我李大人了,不喜欢", "好的"))
    assert rep["rejected"] == 1 and active_names(mem) == [] and mem.core["banned_names"] == ["李大人"]
    assert "不喜欢被叫:李大人" in mem.build_context("")
    for _ in range(2):  # 她再用也不会被记住
        run_batch(mem, clk, {"nicknames": [{"name": "李大人", "explicit": False, "src": [2]}]},
                  dlg("嗯", "李大人今天好"))
    assert mem.core["names"] == []
    run_batch(mem, clk, {"nicknames": [{"name": "李大人", "explicit": True, "src": [1]}]},
              dlg("还是叫我李大人吧"))  # 用户重新明确要求才解禁
    assert active_names(mem) == ["李大人"] and mem.core["banned_names"] == []
    shutil.rmtree(d)


# ------------------------------------------------------------------ 模型输出不可信
def test_malformed_output_is_cleaned_not_crashing():
    mem, clk, d = new_mem()
    resp = {
        "events": [
            {"text": "老李今天买了新手机", "importance": 6, "keywords": None, "gist": 123, "src": [1]},
            {"text": None, "importance": 5, "src": [1]},                     # 无效
            {"text": "老李买了新电脑", "importance": "abc", "src": [1]},      # 无效
            "我是个字符串",                                                   # 不是对象,忽略
            {"text": "老李买了新相机", "importance": "7", "src": [1]}],       # 数字字符串可接受
        "core_candidates": [{"fact": "老李喜欢摄影", "explicit": "false", "src": [1]}],  # 字符串不是布尔值
        "core_updates": [{"index": "0", "new": "x", "src": [1]}, {"index": 5, "new": None, "src": [1]},
                         {"index": 0, "src": [1]}],                          # 都无效
        "nicknames": "不是列表",
        "rejected_nicknames": [{"src": [1]}]}                                # 无效
    rep = run_batch(mem, clk, resp, dlg("我今天买了新手机,还买了新电脑和新相机,我喜欢摄影"))
    assert rep["invalid"] == 7 and rep["events"] == 2
    assert [m["importance"] for m in mem.episodes] == [6, 7]
    assert mem.episodes[0]["keywords"] == [] and mem.episodes[0]["gist"] == "老李今天买了新手机"
    # "false" 字符串绝不当作"明确要求记住"
    assert mem.core["facts"] == [] and mem.core["pending"][0]["explicit"] is False
    shutil.rmtree(d)


def test_commit_failure_rolls_back_everything():
    mem, clk, d = new_mem()
    resp = {"events": [{"text": "老李今天买了新手机", "importance": 6, "src": [1]}],
            "core_candidates": [{"fact": "老李喜欢摄影", "explicit": False, "src": [1]}]}
    llm = lambda p: json.dumps(resp, ensure_ascii=False)

    def boom(*a, **k):
        raise RuntimeError("boom")

    mem._add_core_candidate = boom  # 事件已写入之后才出错
    for role, text in dlg("我今天买了新手机,我喜欢摄影"):
        mem.add_turn(role, text)
    clk.advance(1 / 24)
    assert mem.maybe_consolidate(llm) is False
    assert mem.episodes == [] and len(mem.state["pending"]) == 4 and "commit" in mem.last_report["error"]
    del mem._add_core_candidate  # 恢复后:仍在退避期,不会立刻重试(省调用);过了退避期才重试
    assert mem.maybe_consolidate(llm) is False
    clk.advance(10 / 1440)
    assert mem.maybe_consolidate(llm) is True and len(mem.episodes) == 1 and mem.episodes[0]["recall_count"] == 0
    shutil.rmtree(d)


def test_source_and_grounding_validation():
    mem, clk, d = new_mem()
    turns = [("user", "我今天升职了,特别开心"), ("assistant", "我昨晚梦见去了月球旅行"),
             ("user", "今天吃什么"), ("assistant", "吃火锅吧")]
    rep = run_batch(mem, clk, {
        "events": [
            {"text": "老李说今天升职了", "importance": 8, "src": [1]},          # 有依据:保留
            {"text": "女儿编的一次月球旅行", "importance": 9, "src": [2]},       # 只引用她自己的话
            {"text": "没有依据的事件", "importance": 8},
            {"text": "引用了不存在的编号", "importance": 8, "src": [99]},
            {"text": "老李今天升职了", "importance": 8, "src": [3]}],           # 引用了用户的话,但那句和升职无关
        "core_candidates": [{"fact": "老李是宇航员", "explicit": True, "src": [2]}],
        "nicknames": [{"name": "船长", "explicit": True, "src": [2]},           # 明确要求必须引用用户的话
                      {"name": "队长", "explicit": False, "src": [1]},          # 她自己起的必须引用她的话
                      {"name": "月球人", "explicit": False, "src": [2]}]},      # 引用了她的话,但话里根本没有这个称呼
        turns)
    assert [m["text"] for m in mem.episodes] == ["老李说今天升职了"]
    assert mem.core["facts"] == [] and mem.core["pending"] == [] and mem.core["names"] == []
    assert rep["dropped_no_source"] == 6 and rep["dropped_ungrounded"] == 2 and rep["events"] == 1

    mem2, clk2, d2 = new_mem(grounding_min_overlap=0)  # 关闭字面重合检查
    rep = run_batch(mem2, clk2, {"events": [{"text": "老李今天升职了", "importance": 8, "src": [3]}]}, turns)
    assert rep["events"] == 1 and rep["dropped_ungrounded"] == 0
    shutil.rmtree(d)
    shutil.rmtree(d2)


# ------------------------------------------------------------------ 时间与检索
def test_event_time_is_occurrence_time_not_consolidation_time():
    mem, clk, d = new_mem()
    t0 = clk.t
    run_batch(mem, clk, {"events": [{"text": "老李升职了", "importance": 8, "src": [1]}]},
              dlg("我今天升职了,特别开心"), wait_days=3)   # 攒了 3 天才整理
    ep = mem.episodes[0]
    assert ep["created"] == t0 and ep["stored_at"] - ep["created"] == 3 * DAY
    assert "(3天前)" in mem.build_context("")             # 不会说成"今天"
    shutil.rmtree(d)


def test_only_memories_in_the_prompt_are_consolidated():
    mem, clk, d = new_mem(context_char_budget=25)
    mem._add_event({"text": "项目甲上线很顺利", "importance": 6, "keywords": []})
    mem._add_event({"text": "项目乙延期了", "importance": 5, "keywords": []})
    ctx = mem.build_context("项目")
    assert "项目甲上线很顺利" in ctx and "项目乙延期了" not in ctx   # 预算只放得下第一条
    counts = {m["text"]: m["recall_count"] for m in mem.episodes}
    assert counts == {"项目甲上线很顺利": 1, "项目乙延期了": 0}          # 没读到的不算想起
    shutil.rmtree(d)


def test_retrieve_cap():
    mem, clk, d = new_mem()
    topics = ["项目甲上线", "公园野餐", "海边日出", "电影之夜", "生日蛋糕", "雨天散步", "咖啡拼配", "夜里看星"]
    for t in topics:
        mem._add_event({"text": t, "importance": 5, "keywords": []})
    assert len(mem.retrieve(" ".join(topics))) == 5            # 全部相关:正好 5 条,不再额外加
    assert len(mem.retrieve("今天吃什么")) == 2                # 无关:只带最近 2 条清晰的
    assert len(mem.retrieve("项目甲上线 公园野餐")) <= 5
    shutil.rmtree(d)


def test_context_rendering():
    mem, clk, d = new_mem()
    mem._add_event({"text": "老李带我去海边看了日出", "gist": "和老李看日出", "impression": "看过海",
                    "importance": 8, "keywords": ["海边", "日出"]})
    mem._add_event({"text": "昨晚一起看了电影", "gist": "一起看电影", "importance": 4, "keywords": ["电影"]})
    mem._add_core_candidate("老李喜欢喝咖啡", explicit=True)
    print("\n--- 刚发生 ---\n" + mem.build_context("还记得海边吗"))
    clk.advance(120)
    ctx = mem.build_context("还记得海边吗")
    print("\n--- 120 天后 ---\n" + ctx)
    assert "和老李看日出" in ctx
    assert "老李带我去海边看了日出" not in ctx
    assert "一起看电影" not in ctx
    assert "老李喜欢喝咖啡" in ctx
    shutil.rmtree(d)


def test_failed_consolidation_backs_off_instead_of_retrying_every_turn():
    cfg = {"consolidate_every": 4}  # 对话攒够 4 条就会触发,所以失败后若不退避,每一轮都会再调用一次
    mem, clk, d = new_mem(**cfg)
    calls = []
    good = lambda p: json.dumps({"events": [{"text": "老李今天买了新手机", "importance": 6, "src": [1]}]},
                                ensure_ascii=False)

    def bad(p):
        calls.append(1)
        return "不是JSON"

    for role, text in dlg("我今天买了新手机"):
        mem.add_turn(role, text)
    assert mem.maybe_consolidate(bad) is False and len(calls) == 1
    assert mem.last_report["retry_in_sec"] == 300 and mem.last_report["consecutive_failures"] == 1
    for _ in range(5):  # 退避期内,后面每一轮都不会再调用模型,对话继续累积不丢
        mem.add_turn("user", "继续聊")
        assert mem.maybe_consolidate(bad) is False
    assert len(calls) == 1 and len(mem.state["pending"]) == 9

    clk.advance(301 / DAY)  # 退避期过后重试;再次失败,等待时间翻倍
    assert mem.maybe_consolidate(bad) is False and len(calls) == 2
    assert mem.last_report["retry_in_sec"] == 600 and mem.last_report["consecutive_failures"] == 2

    mem2 = CompanionMemory(d, config=cfg, now_fn=clk)  # 退避状态重启后仍然有效
    assert mem2.maybe_consolidate(bad) is False and len(calls) == 2
    assert mem2.consolidate(good) is True               # 手动直接调用不受退避限制
    assert "retry_after" not in mem2.state and "fail_count" not in mem2.state and len(mem2.episodes) == 1

    for role, text in dlg("今天吃了拉面"):  # 成功后失败计数清零:再失败又从 5 分钟开始
        mem2.add_turn(role, text)
    assert mem2.maybe_consolidate(bad) is False
    assert mem2.last_report["retry_in_sec"] == 300 and mem2.last_report["consecutive_failures"] == 1

    capped, clk2, d2 = new_mem(consolidate_every=4, consolidate_retry_sec=1000, consolidate_retry_max_sec=1500)
    for role, text in dlg("我今天买了新手机"):
        capped.add_turn(role, text)
    for expect in (1000, 1500, 1500):  # 上限生效
        assert capped.maybe_consolidate(bad) is False and capped.last_report["retry_in_sec"] == expect
        clk2.advance(2000 / DAY)
    shutil.rmtree(d)
    shutil.rmtree(d2)


if __name__ == "__main__":
    tests = [(n, f) for n, f in list(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
    print(f"\n全部通过({len(tests)} 组)")
