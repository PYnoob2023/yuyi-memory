"""Offline demonstration. Uses temporary synthetic memories only."""
from tempfile import TemporaryDirectory
from pathlib import Path
from work_memory import WorkMemory
from companion_memory import CompanionMemory
from memory_scheduler import MemoryScheduler


def main():
    with TemporaryDirectory() as folder:
        root = Path(folder)
        work = WorkMemory(root/'work', project='示例项目')
        work.add('goal', '修复登录功能，保持现有页面风格', priority=0)
        work.add('progress', '已定位问题：登录成功后没有刷新用户状态')
        old = work.add('decision', '重写整个界面')
        work.transition(old, 'abandoned', expected_version=1)
        yuyi = CompanionMemory(root/'private')
        yuyi.remember('我们在海边看烟花')
        router = MemoryScheduler(work, yuyi, identity='你叫余忆，称呼用户为朋友，回答简洁。')
        for message, mode, recall in [('继续修复登录功能', 'work', None),
                                      ('还记得我们在海边看烟花吗', 'mixed', None),
                                      ('还记得我们在海边看烟花吗', 'work', False)]:
            packet = router.build_context(message, mode=mode, recall=recall)
            print(f'\n模式={packet.mode} 字符={packet.char_count} 召回往事={len(packet.companion_ids)}')
            print(packet.text)
        router.export_handoff(root/'HANDOFF.md')
        assert '烟花' not in (root/'HANDOFF.md').read_text(encoding='utf-8')


if __name__ == '__main__':
    main()
