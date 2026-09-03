"""Generate XMind file for ch13 learning roadmap."""
import json
import zipfile

# XMind content.json structure
content = {
    'id': 'root',
    'class': 'topic',
    'title': '第 13 章\n后台任务系统',
    'children': {
        'attached': [
            {
                'id': 'learning_path',
                'class': 'topic',
                'title': '学习路线（推荐顺序）',
                'children': {
                    'attached': [
                        {
                            'id': 'step1',
                            'class': 'topic',
                            'title': '第一步：理解后台需求',
                            'children': {
                                'attached': [
                                    {'id': 's1_1', 'class': 'topic', 'title': 'tests/test_ch13_integration.py'},
                                    {'id': 's1_2', 'class': 'topic', 'title': 'tests/test_background.py'},
                                    {'id': 's1_3', 'class': 'topic', 'title': '看后台任务应该做什么'},
                                    {'id': 's1_4', 'class': 'topic', 'title': '理解成功标准'}
                                ]
                            }
                        },
                        {
                            'id': 'step2',
                            'class': 'topic',
                            'title': '第二步：读核心领域模型',
                            'children': {
                                'attached': [
                                    {'id': 's2_1', 'class': 'topic', 'title': 'features/background.py'},
                                    {'id': 's2_2', 'class': 'topic', 'title': 'BackgroundJob 状态机'},
                                    {'id': 's2_3', 'class': 'topic', 'title': 'JobSupervisor 线程管理'},
                                    {'id': 's2_4', 'class': 'topic', 'title': 'BackgroundJobEvent 事件发布'}
                                ]
                            }
                        },
                        {
                            'id': 'step3',
                            'class': 'topic',
                            'title': '第三步：理解工具分流机制',
                            'children': {
                                'attached': [
                                    {'id': 's3_1', 'class': 'topic', 'title': 'core/loop.py _execute_tool'},
                                    {'id': 's3_2', 'class': 'topic', 'title': 'ToolDispatcher 接口'},
                                    {'id': 's3_3', 'class': 'topic', 'title': 'dispatch 返回 None 继续同步执行'}
                                ]
                            }
                        },
                        {
                            'id': 'step4',
                            'class': 'topic',
                            'title': '第四步：集成到 Profile',
                            'children': {
                                'attached': [
                                    {'id': 's4_1', 'class': 'topic', 'title': 'core/profiles.py P13'},
                                    {'id': 's4_2', 'class': 'topic', 'title': 'bootstrap.py 组装逻辑'},
                                    {'id': 's4_3', 'class': 'topic', 'title': 'P13 = P12 + background'}
                                ]
                            }
                        }
                    ]
                }
            },
            {
                'id': 'core_files',
                'class': 'topic',
                'title': '核心文件清单',
                'children': {
                    'attached': [
                        {
                            'id': 'background_py',
                            'class': 'topic',
                            'title': 'features/background.py（后台领域）',
                            'children': {
                                'attached': [
                                    {
                                        'id': 'bg_job',
                                        'class': 'topic',
                                        'title': 'BackgroundJob（状态快照）',
                                        'children': {
                                            'attached': [
                                                {'id': 'job_1', 'class': 'topic', 'title': 'id: canonical UUID'},
                                                {'id': 'job_2', 'class': 'topic', 'title': 'source_tool_call_id'},
                                                {'id': 'job_3', 'class': 'topic', 'title': 'status: 6 种状态'},
                                                {'id': 'job_4', 'class': 'topic', 'title': 'result: 终态携带'}
                                            ]
                                        }
                                    },
                                    {
                                        'id': 'supervisor',
                                        'class': 'topic',
                                        'title': 'JobSupervisor（线程池）',
                                        'children': {
                                            'attached': [
                                                {'id': 'sup_1', 'class': 'topic', 'title': 'capacity/timeout'},
                                                {'id': 'sup_2', 'class': 'topic', 'title': 'submit/cancel/close'}
                                            ]
                                        }
                                    }
                                ]
                            }
                        },
                        {
                            'id': 'loop_py',
                            'class': 'topic',
                            'title': 'core/loop.py（循环集成）'
                        },
                        {
                            'id': 'store',
                            'class': 'topic',
                            'title': 'adapters/background_json.py'
                        }
                    ]
                }
            },
            {
                'id': 'java_mapping',
                'class': 'topic',
                'title': 'Java 对照关系',
                'children': {
                    'attached': [
                        {
                            'id': 'concurrency',
                            'class': 'topic',
                            'title': '并发模型对照',
                            'children': {
                                'attached': [
                                    {'id': 'con_1', 'class': 'topic', 'title': 'Thread = Thread'},
                                    {'id': 'con_2', 'class': 'topic', 'title': 'Event = CountDownLatch'},
                                    {'id': 'con_3', 'class': 'topic', 'title': 'RLock = ReentrantLock'},
                                    {'id': 'con_4', 'class': 'topic', 'title': 'Queue = BlockingQueue'}
                                ]
                            }
                        },
                        {
                            'id': 'state_mgmt',
                            'class': 'topic',
                            'title': '状态管理对照',
                            'children': {
                                'attached': [
                                    {'id': 'st_1', 'class': 'topic', 'title': 'BackgroundJob = 不可变 DTO'},
                                    {'id': 'st_2', 'class': 'topic', 'title': '_controls = ConcurrentHashMap'}
                                ]
                            }
                        }
                    ]
                }
            },
            {
                'id': 'patterns',
                'class': 'topic',
                'title': '设计模式识别',
                'children': {
                    'attached': [
                        {'id': 'state_pattern', 'class': 'topic', 'title': '状态模式（6 种状态）'},
                        {'id': 'observer', 'class': 'topic', 'title': '观察者模式（事件发布）'},
                        {'id': 'strategy', 'class': 'topic', 'title': '策略模式（ToolDispatcher）'},
                        {'id': 'threadpool', 'class': 'topic', 'title': '线程池模式'}
                    ]
                }
            },
            {
                'id': 'concepts',
                'class': 'topic',
                'title': '关键概念理解',
                'children': {
                    'attached': [
                        {'id': 'why', 'class': 'topic', 'title': '为什么需要后台任务'},
                        {'id': 'dispatch', 'class': 'topic', 'title': '工具分流机制'},
                        {'id': 'state', 'class': 'topic', 'title': '状态机设计原则'},
                        {'id': 'event', 'class': 'topic', 'title': '事件发布与去重'},
                        {'id': 'recovery', 'class': 'topic', 'title': '恢复机制'},
                        {'id': 'atomic', 'class': 'topic', 'title': '原子写入保证'}
                    ]
                }
            },
            {
                'id': 'interview',
                'class': 'topic',
                'title': '面试题速查',
                'children': {
                    'attached': [
                        {'id': 'q1', 'class': 'topic', 'title': 'Q1：状态迁移规则'},
                        {'id': 'q2', 'class': 'topic', 'title': 'Q2：ToolDispatcher 返回值语义'},
                        {'id': 'q3', 'class': 'topic', 'title': 'Q3：source_tool_call_id 作用'},
                        {'id': 'q4', 'class': 'topic', 'title': 'Q4：并发容量控制'},
                        {'id': 'q5', 'class': 'topic', 'title': 'Q5：启动恢复机制'},
                        {'id': 'q6', 'class': 'topic', 'title': 'Q6：事件去重'},
                        {'id': 'q7', 'class': 'topic', 'title': 'Q7：超时检测'},
                        {'id': 'q8', 'class': 'topic', 'title': 'Q8：优雅关闭流程'}
                    ]
                }
            }
        ]
    }
}

# Create XMind file
with zipfile.ZipFile('ch13_learning_roadmap.xmind', 'w', zipfile.ZIP_DEFLATED) as xmind:
    xmind.writestr('content.json', json.dumps([content], ensure_ascii=False, indent=2))
    xmind.writestr('metadata.json', json.dumps({
        'creator': {'name': 'Python Agent Course', 'version': '1.0'},
        'modified': '2026-09-02T00:00:00Z'
    }))
    xmind.writestr('manifest.json', json.dumps({
        'file-entries': {
            'content.json': {},
            'metadata.json': {}
        }
    }))

print('ch13_learning_roadmap.xmind created successfully')
