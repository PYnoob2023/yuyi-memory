"""Offline demonstration: a sourced associative path and a promise lifecycle."""
import tempfile
from companion_memory import CompanionMemory
from memory_tools import MemoryTools


def main():
    with tempfile.TemporaryDirectory() as folder:
        memory = CompanionMemory(folder, user_title='朋友', config={'retrieve_k': 2})
        illness = memory.remember('那次发烧住院', importance=8)
        promise = memory.remember('陪你等天亮', importance=8, kind='promise', relationship=2)
        memory.link(illness, promise, '那次发烧住院之后，我们约定陪你等天亮')
        print('输入只有发烧住院，也能沿有依据的关联找到承诺：')
        print(memory.build_context('还记得发烧住院吗'))
        print('\n用户明确确认后更新承诺：')
        assert memory.set_status(promise, 'fulfilled', '陪你等天亮的承诺已经兑现')
        print(memory.build_context('陪我等天亮'))
        print('\n可供模型按需调用的只读工具：')
        print(MemoryTools(memory).run('recall_memory', {'query': '发烧住院', 'char_budget': 400}))
        memory.forget('发烧')
        assert not memory.core['edges']
        print('\n主动删除发烧相关事件后，关联边也已清理。')


if __name__ == '__main__':
    main()
