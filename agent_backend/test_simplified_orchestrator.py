import sys
sys.path.insert(0, ".")

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock
from core.orchestrator import Orchestrator
from core.agents import PlannerAgent, ExecutorAgent, VerifierAgent, DebuggerAgent
from core.task_manager import TaskState
from verifier.verifier import VerificationResult, VerifierOutput
from llm.action_normalizer import Action

class TestSimplifiedOrchestrator(unittest.IsolatedAsyncioTestCase):
    async def test_modular_agents_coordination(self):
        # Mock Config
        config = MagicMock()
        config.air_gap = False
        config.brain_actor_mode = True
        config.use_windows_uia = False
        config.groq_api_key = "dummy-key"
        config.groq_brain_model = "dummy-brain"
        config.ollama_actor_model = None

        # Mock Task
        task = MagicMock()
        task.id = "test-task-123"
        task.goal = "test goal"
        task.state = TaskState.EXECUTING
        task.steps_executed = 0
        task.tokens_used = 0
        task.session_id = "test-session"
        task.is_escalated = False

        # Mock Task Manager
        task_manager = MagicMock()
        task_manager.task = task
        task_manager.start_task = AsyncMock(return_value=task)
        task_manager.get_state = MagicMock(return_value=TaskState.EXECUTING)
        task_manager.record_tokens = MagicMock(return_value=False)
        task_manager.transition = AsyncMock()

        # Mock Router
        router = MagicMock()

        # Mock Sandbox
        sandbox = MagicMock()
        sandbox.take_screenshot = AsyncMock(return_value=b"dummy_screenshot")
        sandbox.get_accessibility_tree = AsyncMock(return_value={})
        sandbox.execute = AsyncMock()

        # Mock Compressor
        compressor = MagicMock()

        # Mock Memory
        memory = MagicMock()
        memory.get_context_for_task = MagicMock(return_value="")

        # Mock Recipe Engine
        recipe_engine = MagicMock()
        recipe_engine.match = MagicMock(return_value=None)

        # Mock Audit
        audit = MagicMock()

        # Mock WS Server
        ws_server = MagicMock()
        ws_server.send = AsyncMock()

        # Instantiate Orchestrator
        orchestrator = Orchestrator(
            config=config,
            task_manager=task_manager,
            router=router,
            sandbox=sandbox,
            verifier=MagicMock(),
            compressor=compressor,
            memory=memory,
            recipe_engine=recipe_engine,
            audit=audit,
            ws_server=ws_server,
        )

        # Use real PlannerAgent, mock the low-level plan request
        orchestrator.planner_agent = PlannerAgent(config, router)
        # Mocking plan method to return the sequence
        orchestrator.planner_agent.plan = AsyncMock(side_effect=["click button", "DONE"])

        # Use real VerifierAgent, mock its internal verifier call
        orchestrator.verifier_agent = VerifierAgent(config)
        ver_output = VerifierOutput(result=VerificationResult.SUCCESS, tier_reached=1, confidence=1.0, reason="success")
        orchestrator.verifier_agent._verifier.verify = AsyncMock(return_value=ver_output)

        # Use real ExecutorAgent, mock _execute_step and verify_coordinate
        orchestrator.executor_agent = ExecutorAgent(config, router, memory, compressor, orchestrator.verifier_agent)
        dummy_action = Action(type="click", target_description="button", element_id="btn", params={})
        orchestrator.executor_agent._execute_step = AsyncMock(return_value=({"reflection": "clicking button"}, [
            '{"action": "click", "element_id": "btn"}'
        ]))
        orchestrator.executor_agent.run_in_sandbox = AsyncMock()

        # Use real DebuggerAgent
        orchestrator.debugger_agent = DebuggerAgent(config, router, task_manager, compressor)

        # Run the worker loop
        orchestrator.MAX_STEPS = 5
        await orchestrator._worker_loop("test goal")

        # Verify interactions
        # 1. Planner was called twice (once for sub-goal, once for DONE)
        self.assertEqual(orchestrator.planner_agent.plan.call_count, 2)
        
        # 2. Executor ran sandbox once
        orchestrator.executor_agent.run_in_sandbox.assert_called_once()
        
        # 3. Verifier verified both the step action and the final DONE state
        self.assertEqual(orchestrator.verifier_agent._verifier.verify.call_count, 2)

    async def test_modular_agents_debugging(self):
        # Mock Config
        config = MagicMock()
        config.air_gap = False
        config.brain_actor_mode = True
        config.use_windows_uia = False
        config.groq_api_key = "dummy-key"
        config.groq_brain_model = "dummy-brain"
        config.ollama_actor_model = None

        # Mock Task
        task = MagicMock()
        task.id = "test-task-456"
        task.goal = "test goal"
        task.state = TaskState.EXECUTING
        task.steps_executed = 0
        task.tokens_used = 0
        task.session_id = "test-session"
        task.is_escalated = False

        # Mock Task Manager
        task_manager = MagicMock()
        task_manager.task = task
        task_manager.start_task = AsyncMock(return_value=task)
        task_manager.get_state = MagicMock(return_value=TaskState.EXECUTING)
        task_manager.record_tokens = MagicMock(return_value=False)
        task_manager.record_failure = MagicMock(return_value=False)
        task_manager.transition = AsyncMock()

        # Mock Router
        router = MagicMock()
        router.should_escalate = MagicMock(return_value=False)

        # Mock Sandbox
        sandbox = MagicMock()
        sandbox.take_screenshot = AsyncMock(return_value=b"dummy_screenshot")
        sandbox.get_accessibility_tree = AsyncMock(return_value={})
        sandbox.execute = AsyncMock()

        # Mock Compressor
        compressor = MagicMock()

        # Mock Memory
        memory = MagicMock()
        memory.get_context_for_task = MagicMock(return_value="")

        # Mock Recipe Engine
        recipe_engine = MagicMock()
        recipe_engine.match = MagicMock(return_value=None)

        # Mock Audit
        audit = MagicMock()

        # Mock WS Server
        ws_server = MagicMock()
        ws_server.send = AsyncMock()

        # Instantiate Orchestrator
        orchestrator = Orchestrator(
            config=config,
            task_manager=task_manager,
            router=router,
            sandbox=sandbox,
            verifier=MagicMock(),
            compressor=compressor,
            memory=memory,
            recipe_engine=recipe_engine,
            audit=audit,
            ws_server=ws_server,
        )

        # Use real PlannerAgent, mock the low-level plan request
        orchestrator.planner_agent = PlannerAgent(config, router)
        orchestrator.planner_agent.plan = AsyncMock(side_effect=["click button", "click button", "DONE"])

        # Use real VerifierAgent, mock its internal verifier call
        orchestrator.verifier_agent = VerifierAgent(config)
        ver_fail = VerifierOutput(result=VerificationResult.FAILURE, tier_reached=1, confidence=1.0, reason="failed click")
        ver_success = VerifierOutput(result=VerificationResult.SUCCESS, tier_reached=1, confidence=1.0, reason="success")
        orchestrator.verifier_agent._verifier.verify = AsyncMock(side_effect=[ver_fail, ver_success, ver_success, ver_success])

        # Use real ExecutorAgent, mock _execute_step and verify_coordinate
        orchestrator.executor_agent = ExecutorAgent(config, router, memory, compressor, orchestrator.verifier_agent)
        orchestrator.executor_agent._execute_step = AsyncMock(return_value=({"reflection": "clicking button"}, [
            '{"action": "click", "element_id": "btn"}'
        ]))
        orchestrator.executor_agent.run_in_sandbox = AsyncMock()

        # Use real DebuggerAgent
        orchestrator.debugger_agent = DebuggerAgent(config, router, task_manager, compressor)

        # Run loop
        orchestrator.MAX_STEPS = 5
        await orchestrator._worker_loop("test goal")

        # Verify
        self.assertEqual(orchestrator.planner_agent.plan.call_count, 3)

if __name__ == '__main__':
    unittest.main()
