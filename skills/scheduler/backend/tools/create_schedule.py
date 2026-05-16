"""Create a new scheduled job."""

from backend.scheduler import scheduler


def execute(agent: dict, args: dict) -> dict:
    agent_id = agent.get('id', '')

    action_config = args.get('action_config', {})
    action_type = args.get('action_type', '')
    # Default target to the calling agent for message-type actions.
    # agent_message is a deprecated alias for static_message.
    if action_type in ('static_message', 'agent_message', 'session_prompt') and 'agent_id' not in action_config:
        action_config['agent_id'] = agent_id

    try:
        result = scheduler.create_schedule(
            name=args['name'],
            owner_type='agent',
            owner_id=agent_id,
            trigger_type=args['trigger_type'],
            trigger_config=args['trigger_config'],
            action_type=args['action_type'],
            action_config=action_config,
            max_runs=args.get('max_runs'),
        )
        return {
            'status': 'success',
            'schedule_id': result['id'],
            'name': result['name'],
            'trigger_type': result['trigger_type'],
            'enabled': bool(result['enabled']),
        }
    except Exception as e:
        return {'status': 'error', 'error': str(e)}
