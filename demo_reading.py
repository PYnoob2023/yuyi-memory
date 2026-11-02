"""Offline demonstration with fictitious entries; no network or personal data."""
import json
import tempfile
from pathlib import Path

from turn_reader import ChatMemory
from companion_memory import CompanionMemory
from project_memory import ProjectMemory


def main():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        memory = CompanionMemory(root/'private')
        memory.remember('蓝桥公司加班后在河边谈过项目', anchors=['蓝桥'])
        target = memory.remember('蓝桥旧约定是晚上十一点休息', anchors=['蓝桥'])
        manager = ProjectMemory(root/'projects', memory, identity='如实回答，不编造共同经历。')
        chat = ChatMemory(manager, system_prompt='你是一个认真倾听的助手。')

        def offline_model(messages):
            print('本轮记忆参考：\n' + messages[-2]['content'])
            return '这是离线演示回复；真实接入时替换这个函数。'

        result = chat.run_turn('又在加班', offline_model, record=False)
        print('召回审计：' + json.dumps(result.context.recall_audit, ensure_ascii=False, indent=2))
        assert target in result.context.companion_ids
        memory.forget('十一点')
        _, after = chat.prepare('又在加班')
        assert target not in after.companion_ids
        print('删除后重新读取：已删除事件没有再次出现。')


if __name__ == '__main__':
    main()

