"""Offline project lifecycle with synthetic data. No API or personal files."""
from pathlib import Path
from tempfile import TemporaryDirectory
from project_memory import ProjectMemory


def main():
    with TemporaryDirectory() as folder:
        manager=ProjectMemory(Path(folder)/'demo',identity='你叫余忆。称呼用户为朋友。')
        a=manager.register('余忆','保存共同经历的记忆工具')
        b=manager.register('圣诞树','用网页呈现手势互动圣诞树')
        manager.work(a).add('goal','修复承诺状态更新，保持现有接口')
        manager.work(a).add('progress','已完成记忆调度，下一步处理取消证据')
        manager.work(b).add('goal','调整星光亮度，保持原有手势')
        manager.update_overview(a,'调度完成，继续完善写入机制',expected_version=1)
        manager.update_overview(b,'网页已上线，准备小幅调整',expected_version=1)
        for message in ('项目列表','进入项目 余忆','继续','切换项目 圣诞树','退出工作','余忆项目怎么样了'):
            packet=manager.build_context(message,recall=False)
            print('\n用户：'+message)
            print(packet.text)
            print('当前项目：'+str(manager.current()['project_id']))


if __name__=='__main__': main()
