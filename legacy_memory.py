"""
companion_memory.py —— 仿人类记忆机制(纯标准库,不依赖任何框架)

三层结构
  1. 近期窗口 recent   : 最近几条对话原文,永远清晰(由调用方放进 messages)
  2. 情景记忆 episodes : 从对话里提炼出的"事件",带重要度,随时间按遗忘曲线衰减
       vivid(清晰,有完整细节) -> faded(模糊,只剩概要) -> impression(只剩一点印象) -> 遗忘
       重要度 >= 7 的事件最终会留下"印象";>= 9 的事件永远留下印象
       被再次提到/再次发生的事件会被巩固(衰减变慢);只有真正放进提示词的记忆才算"被想起"
       每次检索前和每次整理前都会先按时间推进遗忘,不依赖整理是否触发
       事件的时间是它实际发生的时间(被引用的那条用户发言的时间),不是整理的时间
  3. 核心记忆 core     : 很小的一块区域(默认最多 15 条),存关于对方和你们关系的稳定事实
       只有"用户明确说记住"或"在不同整理中重复出现 2 次"才会写入,不是每轮都更新
       用户改主意/纠正时,旧事实会被替换或删除(core_updates);同时清理矛盾的待观察候选,
       并把相关旧事件标注为"当时如此,后来有变化"
       另有"称呼"小区域(最多 5 个):默认称呼由 user_title 决定,她自己起的新称呼
       在不同整理中重复出现 2 次且没被反感,或用户明确要求这样叫,才会被记住;
       用户说"别这样叫我"的称呼会进入禁用列表,之后不会再被记住
  另有 persona.md : 手写的人设,代码不会改它

整理的安全措施(模型输出不可信)
  - 对话带编号,模型必须为每个条目标出依据(src)。代码校验:
      * 事件/核心事实/改动/拒绝称呼必须引用至少一条"用户"的发言;
      * 条目内容必须和被引用的用户发言有实质的字面重合(grounding_min_overlap,设 0 关闭);
        她自己起的称呼必须真的出现在她自己被引用的发言里;
      * 这只能挡住"引用错误/凭空编造",挡不住"用户说的是假设、玩笑、角色扮演却被当成事实",
        后者靠提示词约束,请定期看 episodes.json 抽查。
  - 字段类型先校验清洗(explicit 必须是真正的布尔值,keywords 必须是字符串列表等),
    无效条目跳过并计数;校验通过后才统一写入,写入中途出错则整体回滚,待整理的对话保留以便重试。
  - 为了不破坏"会遗忘",原始发言不会存进记忆,只在入库时校验一次。
  - 整理失败(接口出错、返回无法解析、写入出错)后进入退避:5 分钟后才允许重试,连续失败每次翻倍,
    最长 1 小时,成功后清零。退避状态会保存,重启后仍有效;避免攒够对话后每一轮都重复付费调用。
    手动直接调用 mem.consolidate(llm) 不受退避限制。失败原因和下次重试间隔见 mem.last_report。
  - 每次整理的统计在 mem.last_report:events/core/core_updates/names/rejected 是成功数,
    invalid/dropped_no_source/dropped_ungrounded 是被丢弃数。

省钱/低频
  - 每轮对话只做本地检索,不调用模型
  - 只有累计 N 条对话、或对话停顿超过 30 分钟,才调用一次模型做"整理"

用法
    from companion_memory import CompanionMemory, deepseek_llm
    mem = CompanionMemory("memory_data", user_title="老李")   # user_title = 默认称呼,她之后可自己增加别的称呼

    # 每次收到用户消息:
    mem.maybe_consolidate(deepseek_llm)          # 先看要不要整理(多数时候什么都不做)
    system_prompt = mem.build_context(user_msg)  # 人设 + 称呼 + 核心记忆 + 此刻想起的往事
    messages = [{"role": "system", "content": system_prompt}] + mem.recent_messages()
    messages.append({"role": "user", "content": user_msg})
    reply = ...                                  # 调你的模型
    mem.add_turn("user", user_msg); mem.add_turn("assistant", reply)

使用限制
  - 本模块不是线程安全的。QQ 等网关请让同一个会话的消息排队依次处理(一个会话一个 worker),
    不要让两条消息同时调用 add_turn / build_context / maybe_consolidate。
  - 触发整理的那一轮,会在回复前多等一次模型调用(几秒);平时的轮次不受影响。

手动操作(都会立即保存)
    mem.remember("一定要记住的事", importance=9)   # 直接写入一条事件
    mem.forget("关键词")                           # 彻底忘记:长期记忆 + 待整理对话 + 近期窗口里含该词的内容
    mem.forget("关键词", chat=False)               # 只删长期记忆,不动聊天窗口
    mem.reject_name("李大人")                      # 禁用某个称呼
"""
from __future__ import annotations

import copy
import json
import math
import os
import re
import time
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

DAY = 86400.0

CONFIG = dict(
    consolidate_every=20,        # 累计多少条对话后整理一次
    idle_consolidate_sec=1800,   # 或对话停顿多久后整理
    min_turns_to_consolidate=4,  # 少于这个条数不值得调用一次模型
    recent_keep=8,               # 近期原文窗口(条)
    min_importance=3,            # 低于此值的事件不入库
    stability_base=2.0,          # 稳定度 S(天) = base * growth ** importance
    stability_growth=1.6,        # 重要度 3≈8天 5≈21天 7≈54天 9≈140天 10≈220天
    vivid_th=0.6,                # 保留率 >= 此值: 清晰
    faded_th=0.2,                # >= 此值: 模糊;更低: 只剩印象或遗忘
    forget_th=0.03,              # 印象再衰减到此值以下: 彻底遗忘
    impression_min_importance=7, # 重要度达到此值才会留下印象
    permanent_importance=9,      # 达到此值的印象永不消失
    decay_interval_sec=600,      # 检索前自动衰减的最短间隔
    core_max=15,                 # 核心记忆条数上限
    core_promote_count=2,        # 非明确要求的候选,重复出现几次才写入核心
    pending_expire_days=30,
    retrieve_k=5,                # 每轮最多想起几条往事(含"近期总是记得"的那几条)
    relevance_th=0.12,
    context_char_budget=1200,    # 往事部分的字数预算
    names_max=5,                 # 除默认称呼外,最多记住几个别的称呼
    name_promote_count=2,        # 她自己起的称呼,在不同整理中出现几次才记住
    name_max_len=8,
    banned_names_max=10,
    grounding_min_overlap=1,     # 条目与被引用的用户发言至少要有几个实质(非常用词)的相邻二字重合;0=不检查
    consolidate_retry_sec=300,       # 整理失败后至少隔多久再试(连续失败每次翻倍)
    consolidate_retry_max_sec=3600,  # 退避时间的上限
)

DEFAULT_PERSONA = """# 人设(手写,代码不会修改这个文件)
- 名字:小○(改成你想要的名字)
- 身份:{user_title}养的AI女儿,性格____(例如:活泼、有点嘴硬、爱吐槽)
- 说话风格:____(例如:口语化、偶尔撒娇、不说教)
- 称呼:默认叫对方"{user_title}";你也可以自己给对方起新的称呼(比如聊天里冒出来的昵称),用得自然、对方不反感,就会被记住
- 底线:不编造没发生过的事;不确定时就说"好像""记不太清了"
"""

EXTRACT_PROMPT = """你是记忆整理器。下面是最近的一段对话(发生于 {date}),每条前面有编号。
只提取值得长期记住的内容,日常寒暄、重复闲聊不要提取。输出 JSON,格式:
{{"events":[{{"text":"事件的完整描述(40字内)","gist":"一句话概要(15字内)","impression":"最模糊的一点印象(10字内,像隔了很久只记得大概)","importance":整数1-10,"keywords":["关键词,含2~3个近义说法"],"src":[依据的对话编号]}}],
 "core_candidates":[{{"fact":"关于{user_title}或你们关系的稳定事实","explicit":true或false,"src":[编号]}}],
 "core_updates":[{{"index":已有核心记忆的编号,"new":"改后的事实;要删除则为null","src":[编号]}}],
 "nicknames":[{{"name":"称呼","explicit":true或false,"src":[编号]}}],
 "rejected_nicknames":[{{"name":"称呼","src":[编号]}}]}}
规则:
1. 每个条目必须用 src 标出依据的对话编号。只记录{user_title}说过或明确认可的内容;我(女儿)单方面说的话,{user_title}没有回应或确认的,不要当作事实或共同经历记录。条目的描述请尽量沿用{user_title}原话里的词,方便核对。
2. 只有{user_title}明确陈述为真的事才记录。提问、假设、玩笑、角色扮演、引用别人的话、被{user_title}否认或纠正的内容都不要记录;"我没有……""不是……"是否定,不能当作肯定来记录。
3. importance 标准: 1-2 寒暄; 3-4 一般日常; 5-6 值得记的事; 7-8 重要(情绪强烈/生活转折/第一次/承诺); 9-10 终身难忘。
4. core_candidates 只放长期稳定的事实(家人、工作、重要喜好、约定),一次性的事不要放;用户明确说"记住/别忘了"时 explicit 为 true(必须是布尔值 true/false,不要加引号)。
5. 用户改了主意或纠正了某条已有核心记忆(例如从喜欢变成不喜欢,或说"这个别记了"),用 core_updates 修改或删除那一条(删除时 new 写 null),不要用 core_candidates 再添一条相反的。
6. nicknames 只放"我(女儿)用来称呼{user_title}的称呼":用户明确要求这样叫(explicit 为 true,src 指向用户的话),或我自己新起的称呼且用户没有反感(explicit 为 false,src 指向我用到这个称呼的话)。不要重复已有称呼。
7. rejected_nicknames 放用户表示不喜欢、不要再这样叫的称呼(src 指向用户的话)。
没有的类别留空数组。
已有核心记忆(编号从 0 开始):
{core}
已有称呼: {names}
已禁用称呼(不要再提取): {banned}

对话:
{convo}
"""

_NEG = ("不", "没", "别", "无", "讨厌", "戒")
_NEG_RE = re.compile("|".join(_NEG))
# 太常见、几乎出现在任何对话里的相邻二字,不能作为"确实说过这件事"的证据
_STOP_BIGRAMS = {"今天", "什么", "我们", "你们", "他们", "这个", "那个", "可以", "没有", "不是",
                 "就是", "还是", "一个", "已经", "因为", "所以", "觉得", "知道", "时候", "现在"}


# ---------------------------------------------------------------- 工具函数
def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _bigrams(s: str) -> set:
    s = re.sub(r"\s+", "", (s or "").lower())
    return {s[i:i + 2] for i in range(len(s) - 1)} or ({s} if s else set())


def _content_bigrams(s: str) -> set:
    return {b for b in _bigrams(s) if b not in _STOP_BIGRAMS}

_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_ASCII_RUN = re.compile(r"[a-z0-9]{2,}")


def _tokens(s: str) -> set:
    """中文按两个字、英文和数字按整词；避免 hello 撞上 scheduler 里的 he/ll。"""
    s = (s or "").lower()
    out = set()
    for run in _CJK_RUN.findall(s):
        for i in range(len(run) - 1):
            bg = run[i:i + 2]
            if bg not in _STOP_BIGRAMS:
                out.add(bg)
    for word in _ASCII_RUN.findall(s):
        out.add("w:" + word)
    return out


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _neg(s: str) -> bool:
    return bool(_NEG_RE.search(s))


def _same(a: str, b: str) -> bool:
    """两句话是不是同一件事。一句带否定、一句不带时不算同一件事(避免"喜欢咖啡"强化"不喜欢咖啡")。"""
    return _neg(a) == _neg(b) and _jaccard(_bigrams(a), _bigrams(b)) > 0.5


def _conflicts(a: str, b: str) -> bool:
    """两句话说的是同一件事但一句肯定一句否定。"""
    return _neg(a) != _neg(b) and _jaccard(_bigrams(_NEG_RE.sub("", a)), _bigrams(_NEG_RE.sub("", b))) >= 0.6


def _as_str(v, max_len: int = 200):
    return v.strip()[:max_len] if isinstance(v, str) and v.strip() else None


def _as_int(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip())
    return None


def _as_str_list(v, n: int) -> list:
    if not isinstance(v, list):
        return []
    return [s for s in (_as_str(x, 20) for x in v) if s][:n]


def _parse_json(raw: str) -> dict:
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, flags=re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def deepseek_llm(prompt: str, model: str = "deepseek-flash",
                 api_key: str | None = None, base: str = "https://api.deepseek.com") -> str:
    """整理记忆用的模型调用(OpenAI 兼容格式)。需要环境变量 DEEPSEEK_API_KEY。"""
    key = api_key or os.environ["DEEPSEEK_API_KEY"]
    body = {"model": model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"}}
    req = urllib.request.Request(
        base + "/chat/completions", data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)["choices"][0]["message"]["content"]


# ---------------------------------------------------------------- 主类
class CompanionMemory:
    STAGE_ORDER = {"vivid": 0, "faded": 1, "impression": 2}

    def __init__(self, data_dir="memory_data", config=None, now_fn=time.time, user_title="老李"):
        self.cfg = {**CONFIG, **(config or {})}
        self.now = now_fn
        self.user_title = user_title
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.persona_path = self.dir / "persona.md"
        if not self.persona_path.exists():
            self.persona_path.write_text(DEFAULT_PERSONA.format(user_title=user_title), encoding="utf-8")
        self._ep_path = self.dir / "episodes.json"
        self._core_path = self.dir / "core_facts.json"
        self._state_path = self.dir / "state.json"
        self.episodes: list = _load(self._ep_path, [])
        self.core: dict = _load(self._core_path, {"facts": [], "pending": []})
        self.core.setdefault("names", [])         # 称呼:{name, count, explicit, active, last_seen}
        self.core.setdefault("banned_names", [])  # 用户不喜欢的称呼
        self.state: dict = _load(self._state_path, {"recent": [], "pending": []})
        self.last_report: dict = {}               # 最近一次整理的统计,方便排查
        self._last_decay = float("-inf")
        self.decay()

    # ------------------------------------------------ 遗忘曲线
    def stability(self, m) -> float:
        c = self.cfg
        return c["stability_base"] * c["stability_growth"] ** m["importance"] * (1 + 0.3 * m["recall_count"])

    def retention(self, m, now=None) -> float:
        now = now or self.now()
        age_days = max(0.0, now - m["last_recalled"]) / DAY
        return math.exp(-age_days / self.stability(m))

    def decay(self) -> None:
        """按时间推进遗忘。阶段只会往后走:忘掉的细节不会自己回来。同时清理过期的候选。"""
        c, now, keep, changed = self.cfg, self.now(), [], False
        for m in self.episodes:
            r = self.retention(m, now)
            imp = m["importance"]
            if r >= c["vivid_th"]:
                target = "vivid"
            elif r >= c["faded_th"]:
                target = "faded"
            elif imp >= c["permanent_importance"]:
                target = "impression"
            elif imp >= c["impression_min_importance"] and r >= c["forget_th"]:
                target = "impression"
            else:
                changed = True
                continue  # 彻底遗忘
            if self.STAGE_ORDER[target] > self.STAGE_ORDER[m["stage"]]:
                changed = True
                m["stage"] = target
                if target == "faded":
                    m["text"] = None      # 细节丢失,只剩概要
                elif target == "impression":
                    m["text"] = None
                    m["gist"] = None      # 只剩一点印象
            keep.append(m)
        self.episodes = keep
        expire = c["pending_expire_days"] * DAY
        pending = [p for p in self.core["pending"] if now - p["last_seen"] < expire]
        names = [n for n in self.core["names"] if n["active"] or now - n["last_seen"] < expire]
        if len(pending) != len(self.core["pending"]) or len(names) != len(self.core["names"]):
            changed = True
        self.core["pending"], self.core["names"] = pending, names
        self._last_decay = now
        if changed:
            self._save_all()

    def _decay_if_due(self) -> None:
        if self.now() - self._last_decay >= self.cfg["decay_interval_sec"]:
            self.decay()

    # ------------------------------------------------ 写入对话(本地,不调用模型)
    def add_turn(self, role: str, text: str) -> None:
        t = {"role": role, "text": text, "t": self.now()}
        self.state["recent"] = (self.state["recent"] + [t])[-self.cfg["recent_keep"]:]
        self.state["pending"] = (self.state["pending"] + [t])[-200:]
        _save(self._state_path, self.state)

    def recent_messages(self) -> list:
        return [{"role": t["role"], "content": t["text"]} for t in self.state["recent"]]

    # ------------------------------------------------ 低频整理(才会调用模型)
    def maybe_consolidate(self, llm) -> bool:
        pend = self.state["pending"]
        if len(pend) < self.cfg["min_turns_to_consolidate"]:
            return False
        if self.now() < self.state.get("retry_after", 0):
            return False  # 上次整理失败,还在退避期:不重复调用模型
        idle = self.now() - pend[-1]["t"] > self.cfg["idle_consolidate_sec"]
        if len(pend) < self.cfg["consolidate_every"] and not idle:
            return False
        return self.consolidate(llm)

    def consolidate(self, llm) -> bool:
        pend = self.state["pending"]
        if not pend:
            return False
        self.decay()  # 先推进遗忘、清理过期候选,再处理新内容:过期的东西不会被这一批"续命"
        who = {"user": self.user_title, "assistant": "我(女儿)"}
        convo = "\n".join(f"[{i}] {who.get(t['role'], t['role'])}: {t['text']}" for i, t in enumerate(pend, 1))
        core = "\n".join(f"[{i}] {f['fact']}" for i, f in enumerate(self.core["facts"])) or "(空)"
        names = "、".join([self.user_title] + [n["name"] for n in self.core["names"] if n["active"]])
        banned = "、".join(self.core["banned_names"]) or "(无)"
        prompt = EXTRACT_PROMPT.format(
            date=datetime.fromtimestamp(pend[0]["t"]).strftime("%Y-%m-%d"),
            user_title=self.user_title, core=core, names=names, banned=banned, convo=convo)
        try:
            data = _parse_json(llm(prompt))
            if not isinstance(data, dict):
                raise ValueError("not an object")
        except Exception as e:
            return self._consolidate_failed({"error": f"llm/parse: {e!r}"})  # 保留待整理的对话,退避后再试
        rep = {"events": 0, "core": 0, "core_updates": 0, "names": 0, "rejected": 0,
               "invalid": 0, "dropped_no_source": 0, "dropped_ungrounded": 0}
        snapshot = copy.deepcopy((self.episodes, self.core))
        try:
            plan = self._plan(data, pend, rep)   # 只校验清洗,不改动记忆
            self._commit(plan, rep)              # 统一写入
        except Exception as e:
            self.episodes, self.core = snapshot  # 中途出错:整体回滚,待整理的对话保留
            return self._consolidate_failed({"error": f"commit: {e!r}"})
        self.last_report = rep
        self.state["pending"] = []
        self.state.pop("retry_after", None)  # 成功后清零退避
        self.state.pop("fail_count", None)
        self.decay()
        self._save_all()
        return True

    def _consolidate_failed(self, report: dict) -> bool:
        """整理失败:保留待整理的对话,并按连续失败次数指数退避(5 分钟、10 分钟、20 分钟……上限 1 小时)。"""
        n = self.state.get("fail_count", 0) + 1
        delay = min(self.cfg["consolidate_retry_max_sec"], self.cfg["consolidate_retry_sec"] * 2 ** (n - 1))
        self.state["fail_count"] = n
        self.state["retry_after"] = self.now() + delay
        self.last_report = {**report, "retry_in_sec": delay, "consecutive_failures": n}
        _save(self._state_path, self.state)
        return False

    # ---- 第一步:校验与清洗(纯函数式,不改动记忆)
    def _plan(self, data: dict, pend: list, rep: dict) -> dict:
        c = self.cfg
        roles = [t["role"] for t in pend]
        texts = [t["text"] for t in pend]
        times = [t["t"] for t in pend]
        snapshot = list(self.core["facts"])

        def items(key):
            v = data.get(key)
            return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []

        def cited(item):
            src = item.get("src")
            if not isinstance(src, list):
                return []
            return sorted({i for i in src if isinstance(i, int) and not isinstance(i, bool) and 1 <= i <= len(roles)})

        def has(item, role):
            return any(roles[i - 1] == role for i in cited(item))

        def grounded(bg: set, item) -> bool:
            if c["grounding_min_overlap"] <= 0:
                return True
            return any(len(bg & _content_bigrams(texts[i - 1])) >= c["grounding_min_overlap"]
                       for i in cited(item) if roles[i - 1] == "user")

        def flag(item) -> bool:
            v = item.get("explicit", False)
            if isinstance(v, bool):
                return v
            rep["invalid"] += 1  # 例如 "false" 字符串:当作 False,绝不当作真
            return False

        def no_source():
            rep["dropped_no_source"] += 1

        def ungrounded():
            rep["dropped_ungrounded"] += 1

        plan = {"updates": [], "rejected": [], "events": [], "cands": [], "names": []}

        for up in items("core_updates"):  # 纠错:替换或删除已有核心事实
            idx = _as_int(up.get("index"))
            if idx is None or not 0 <= idx < len(snapshot) or "new" not in up:
                rep["invalid"] += 1
                continue
            new = up["new"]
            if new is not None and _as_str(new, 80) is None:
                rep["invalid"] += 1
                continue
            new = _as_str(new, 80) if new is not None else None
            if not has(up, "user"):
                no_source()
                continue
            if new is not None and not grounded(_content_bigrams(new), up):
                ungrounded()
                continue
            plan["updates"].append((snapshot[idx], new))

        for rj in items("rejected_nicknames"):  # 称呼被拒
            name = _as_str(rj.get("name"), 40)
            if name is None:
                rep["invalid"] += 1
                continue
            if not has(rj, "user"):
                no_source()
                continue
            if not any(name in texts[i - 1] for i in cited(rj)):
                ungrounded()
                continue
            plan["rejected"].append(name)

        seen = []
        for ev in items("events"):  # 事件
            text, imp = _as_str(ev.get("text"), 80), _as_int(ev.get("importance"))
            if text is None or imp is None:
                rep["invalid"] += 1
                continue
            if not has(ev, "user"):
                no_source()
                continue
            kws = _as_str_list(ev.get("keywords"), 8)
            if not grounded(_content_bigrams(text + " " + " ".join(kws)), ev):
                ungrounded()
                continue
            if any(_same(text, k) for k in seen):  # 同一批里重复的只算一次
                continue
            seen.append(text)
            first_user = min(i for i in cited(ev) if roles[i - 1] == "user")
            plan["events"].append({
                "text": text, "importance": imp, "keywords": kws,
                "gist": _as_str(ev.get("gist"), 30), "impression": _as_str(ev.get("impression"), 20),
                "occurred_at": times[first_user - 1]})  # 事件发生的时间,不是整理的时间

        seen = []
        for cand in items("core_candidates"):  # 核心候选
            fact = _as_str(cand.get("fact"), 80)
            if fact is None:
                rep["invalid"] += 1
                continue
            explicit = flag(cand)
            if not has(cand, "user"):
                no_source()
                continue
            if not grounded(_content_bigrams(fact), cand):
                ungrounded()
                continue
            if any(_same(fact, k) for k in seen):  # 同一批里重复的只算一次
                continue
            seen.append(fact)
            plan["cands"].append((fact, explicit))

        seen_names = set()
        for nk in items("nicknames"):  # 称呼
            name = _as_str(nk.get("name"), 40)
            if name is None:
                rep["invalid"] += 1
                continue
            explicit = flag(nk)
            if len(name) > c["name_max_len"] or name in seen_names:
                continue
            role = "user" if explicit else "assistant"
            if not has(nk, role):
                no_source()
                continue
            if not any(name in texts[i - 1] for i in cited(nk) if roles[i - 1] == role):
                ungrounded()
                continue
            seen_names.add(name)
            plan["names"].append((name, explicit))
        return plan

    # ---- 第二步:统一写入
    def _commit(self, plan: dict, rep: dict) -> None:
        now = self.now()
        for f, new in plan["updates"]:
            if not any(f is x for x in self.core["facts"]):
                continue
            old = f["fact"]
            if new is None:
                self.core["facts"] = [x for x in self.core["facts"] if x is not f]
            else:
                f["fact"], f["last_seen"], f["explicit"] = new, now, True
            self._after_correction(old, new)
            rep["core_updates"] += 1
        for name in plan["rejected"]:
            if self._reject_name(name):
                rep["rejected"] += 1
        for ev in plan["events"]:
            if self._add_event(ev, occurred_at=ev["occurred_at"]):
                rep["events"] += 1
        for fact, explicit in plan["cands"]:
            self._add_core_candidate(fact, explicit)
            rep["core"] += 1
        for name, explicit in plan["names"]:
            if self._add_name(name, explicit):
                rep["names"] += 1

    def _after_correction(self, old: str, new) -> None:
        """一条核心事实被改/删之后:清理与旧说法相同或矛盾的待观察候选,并把相关旧事件标注"后来有变化"。"""
        self.core["pending"] = [
            p for p in self.core["pending"]
            if not (_same(p["fact"], old) or _conflicts(p["fact"], old) or (new and _conflicts(p["fact"], new)))]
        old_bg = _content_bigrams(old)
        if not old_bg:
            return
        for m in self.episodes:
            own = _content_bigrams(" ".join(x for x in (m["text"], m["gist"], m["impression"]) if x))
            if len(old_bg & own) / len(old_bg) >= 0.5:
                m["corrected"] = True

    # ------------------------------------------------ 手动操作(立即保存)
    def remember(self, text: str, importance: int = 8) -> None:
        """手动写入一条事件(例如用户说"这个一定要记住")。"""
        self._add_event({"text": text, "importance": importance})
        self._save_all()

    def forget(self, keyword: str, chat: bool = True) -> int:
        """彻底忘记含该关键词的内容,返回处理条数。
        长期记忆(事件、核心事实、待观察候选)总是删除;chat=True 时,待整理对话和近期窗口里含该词的发言
        也会被替换成"已删除"的占位(保留角色和顺序),否则它们还会进入聊天上下文、或在下次整理时重新入库。"""
        keyword = keyword.strip()
        if not keyword:
            return 0
        hit = lambda m: any(keyword in (m.get(k) or "") for k in ("text", "gist", "impression")) \
            or any(keyword in kw for kw in m.get("keywords", []))
        n0 = len(self.episodes) + len(self.core["facts"]) + len(self.core["pending"])
        self.episodes = [m for m in self.episodes if not hit(m)]
        self.core["facts"] = [f for f in self.core["facts"] if keyword not in f["fact"]]
        self.core["pending"] = [p for p in self.core["pending"] if keyword not in p["fact"]]
        n = n0 - (len(self.episodes) + len(self.core["facts"]) + len(self.core["pending"]))
        if chat:
            masked = set()
            for lst in (self.state["recent"], self.state["pending"]):
                for t in lst:
                    if keyword in t["text"]:
                        t["text"] = "(这段内容已按要求删除)"
                        masked.add((t["t"], t["role"]))
            n += len(masked)
        self._save_all()
        return n

    def reject_name(self, name: str) -> bool:
        """禁用一个称呼:从已记住的称呼里删除,并且之后不会再被记住(除非用户再明确要求)。立即保存。"""
        ok = self._reject_name(name)
        if ok:
            self._save_all()
        return ok

    def _reject_name(self, name: str) -> bool:
        name = name.strip()
        if not name or name == self.user_title:
            return False
        self.core["names"] = [n for n in self.core["names"] if n["name"] != name]
        banned = self.core["banned_names"]
        if name not in banned:
            banned.append(name)
            del banned[:-self.cfg["banned_names_max"]]
        return True

    # ------------------------------------------------ 内部写入
    def _add_event(self, ev: dict, occurred_at=None) -> bool:
        try:
            imp = max(1, min(10, int(ev.get("importance", 0))))
        except (TypeError, ValueError):
            return False
        text = str(ev.get("text", "")).strip()
        if imp < self.cfg["min_importance"] or not text:
            return False
        now = self.now()
        t = occurred_at if occurred_at is not None else now
        for m in self.episodes:  # 重复发生 = 巩固已有记忆,而不是新增一条
            if m.get('kind', 'event') == ev.get('kind', 'event') and _same(text, m["text"] or m["gist"] or m["impression"] or ""):
                m["importance"] = max(m["importance"], imp)
                m["recall_count"] += 1
                m["last_recalled"] = max(m["last_recalled"], t)
                return True
        gist = str(ev.get("gist") or text[:15])
        self.episodes.append({
            "id": uuid.uuid4().hex[:8], "text": text, "gist": gist,
            "impression": str(ev.get("impression") or gist[:10]),
            "importance": imp, "keywords": [str(k) for k in (ev.get("keywords") or [])][:8],
            "created": t, "stored_at": now,        # created = 发生时间;stored_at = 入库(整理)时间
            "last_recalled": t, "last_touch": 0.0,
            "recall_count": 0, "stage": "vivid"})
        return True

    def _add_core_candidate(self, fact: str, explicit: bool) -> None:
        fact = fact.strip()
        if not fact:
            return
        now = self.now()
        for f in self.core["facts"]:
            if _same(fact, f["fact"]):
                f["count"] += 1
                f["last_seen"] = now
                return
        for p in self.core["pending"]:
            if _same(fact, p["fact"]):
                p["count"] += 1
                p["last_seen"] = now
                p["explicit"] = p["explicit"] or explicit
                self._maybe_promote(p)
                return
        # 新说法覆盖与之矛盾的旧候选(后说的为准)
        self.core["pending"] = [p for p in self.core["pending"] if not _conflicts(fact, p["fact"])]
        p = {"fact": fact, "count": 1, "explicit": explicit, "created": now, "last_seen": now}
        self.core["pending"].append(p)
        self._maybe_promote(p)

    def _maybe_promote(self, p: dict) -> None:
        if not (p["explicit"] or p["count"] >= self.cfg["core_promote_count"]):
            return
        self.core["pending"] = [x for x in self.core["pending"] if x is not p]
        old = [f for f in self.core["facts"] if _conflicts(f["fact"], p["fact"])]  # 晋升的新说法取代矛盾的旧事实
        for f in old:
            self._after_correction(f["fact"], p["fact"])
        facts = [f for f in self.core["facts"] if not any(f is o for o in old)]
        facts.append(p)
        if len(facts) > self.cfg["core_max"]:  # 满了就挤掉最不重要的,但不会挤掉刚晋升的这一条
            victim = min((f for f in facts if f is not p),
                         key=lambda f: (f["explicit"], f["count"], f["last_seen"]))
            facts = [f for f in facts if f is not victim]
        self.core["facts"] = facts

    def _add_name(self, name: str, explicit: bool) -> bool:
        """称呼:用户明确要求立刻记住;她自己起的,要在不同整理里重复出现才记住。"""
        c, name, now = self.cfg, name.strip(), self.now()
        if not name or len(name) > c["name_max_len"] or name == self.user_title:
            return False
        banned = self.core["banned_names"]
        if name in banned:
            if not explicit:
                return False
            banned.remove(name)  # 用户重新明确要求,解除禁用
        for n in self.core["names"]:
            if n["name"] == name:
                n["count"] += 1
                n["last_seen"] = now
                n["explicit"] = n["explicit"] or explicit
                n["active"] = n["active"] or n["explicit"] or n["count"] >= c["name_promote_count"]
                self._trim_names(keep=n)
                return True
        n = {"name": name, "count": 1, "explicit": explicit, "last_seen": now,
             "active": explicit or c["name_promote_count"] <= 1}
        self.core["names"].append(n)
        self._trim_names(keep=n)
        return True

    def _trim_names(self, keep: dict) -> None:
        """已记住的称呼超过上限时,挤掉最不重要的,但不会挤掉刚刚加入/激活的这一个。"""
        names = self.core["names"]
        active = [n for n in names if n["active"]]
        while len(active) > self.cfg["names_max"]:
            others = [n for n in active if n is not keep]
            if not others:
                break
            victim = min(others, key=lambda n: (n["explicit"], n["count"], n["last_seen"]))
            names = [n for n in names if n is not victim]
            active = [n for n in active if n is not victim]
        self.core["names"] = names

    # ------------------------------------------------ 检索(本地,每轮都跑,零成本)
    @staticmethod
    def _relevance(q: set, m: dict) -> float:
        pieces = [m["text"], m["gist"], m["impression"], " ".join(m["keywords"])]
        bg = _tokens(" ".join(p for p in pieces if p))
        return len(q & bg) / max(1, min(len(q), len(bg))) if q and bg else 0.0

    def _retrieve_scored(self, query: str = "") -> list:
        """返回 [(记忆, 相关度)],不做任何巩固。"""
        self._decay_if_due()  # 先推进遗忘,再检索:过期的细节不会被读出
        c, now = self.cfg, self.now()
        q = _tokens(query)
        scored = []
        for m in self.episodes:
            r, rel = self.retention(m, now), self._relevance(q, m)
            scored.append((rel + 0.4 * r + 0.03 * m["importance"], rel, m))
        scored.sort(key=lambda x: -x[0])
        k = c["retrieve_k"]
        picked = [x for x in scored if x[1] >= c["relevance_th"]][:k]
        ids = {x[2]["id"] for x in picked}
        slots = min(2, k - len(picked))  # 近期还清晰的事总是记得,但总数不超过 retrieve_k
        if slots > 0:
            picked += sorted((x for x in scored if x[2]["stage"] == "vivid" and x[2]["id"] not in ids),
                             key=lambda x: -x[2]["created"])[:slots]
        return [(x[2], x[1]) for x in picked]

    def retrieve(self, query: str = "") -> list:
        return [m for m, _ in self._retrieve_scored(query)]

    def _ago(self, ts: float) -> str:
        d = (self.now() - ts) / DAY
        if d < 0.5:
            return "刚才/今天"
        if d < 1.5:
            return "昨天"
        if d < 14:
            return f"{int(d)}天前"
        if d < 60:
            return f"{int(d // 7)}周前"
        if d < 700:
            return f"{int(d // 30)}个月前"
        return f"{int(d // 365)}年前"

    def _render(self, m: dict) -> str:
        ago = self._ago(m["created"]) + (",当时如此,后来有变化" if m.get("corrected") else "")
        if m["stage"] == "vivid":
            return f"- ({ago}) {m['text']}"
        if m["stage"] == "faded":
            return f"- ({ago},记得有点模糊) {m['gist']}"
        return f"- ({ago},只隐约记得) {m['impression']}"

    def build_context(self, user_msg: str = "") -> str:
        persona = self.persona_path.read_text(encoding="utf-8").strip()
        parts = [persona]
        extra = [n["name"] for n in self.core["names"] if n["active"]]
        banned = self.core["banned_names"]
        if extra or banned:
            sec = f"默认叫“{self.user_title}”" + (f";也叫过:{'、'.join(extra)}" if extra else "")
            sec = "## 称呼\n" + sec + "。按当下的心情自然选用,也可以自己想新的称呼。"
            if banned:
                sec += f"\n对方不喜欢被叫:{'、'.join(banned)},不要再用。"
            parts.append(sec)
        if self.core["facts"]:
            parts.append(f"## 我记得的关于{self.user_title}和我们的事\n" +
                         "\n".join(f"- {f['fact']}" for f in self.core["facts"]))
        lines, used, chosen = [], 0, []
        for m, rel in self._retrieve_scored(user_msg):
            line = self._render(m)
            if used + len(line) > self.cfg["context_char_budget"]:
                break
            lines.append(line)
            chosen.append((m, rel))
            used += len(line)
        now = self.now()
        for m, rel in chosen:  # 只有真正放进提示词的相关记忆才算"被想起"而巩固
            if rel >= self.cfg["relevance_th"] and now - m["last_touch"] > 3600:
                m["recall_count"] += 1
                m["last_recalled"] = m["last_touch"] = now
        if lines:
            parts.append("## 此刻想起的往事\n" + "\n".join(lines) +
                         "\n(按清晰程度自然地说:模糊的用“好像”“记不太清了”,不要补全不记得的细节;"
                         "不必每次都主动提起往事。)")
        _save(self._ep_path, self.episodes)  # 保存被巩固的记忆
        return "\n\n".join(parts)

    def _save_all(self) -> None:
        _save(self._ep_path, self.episodes)
        _save(self._core_path, self.core)
        _save(self._state_path, self.state)
