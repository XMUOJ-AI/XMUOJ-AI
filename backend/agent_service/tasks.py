import dramatiq


@dramatiq.actor(queue_name="agent", max_retries=0, time_limit=35000)
def execute_agent_run(run_id):
    from .runtime import execute
    execute(run_id)
