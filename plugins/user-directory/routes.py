"""
User Directory -- Flask route handlers.

REST API:
  GET    /api/user-directory/users              List/search users
  POST   /api/user-directory/users              Create user
  GET    /api/user-directory/users/<id>          Get user detail
  PUT    /api/user-directory/users/<id>          Update user
  DELETE /api/user-directory/users/<id>          Soft delete user
  POST   /api/user-directory/users/<id>/block    Block/unblock user
  GET    /api/user-directory/users/<id>/contacts     List contacts
  POST   /api/user-directory/users/<id>/contacts     Add contact
  PUT    /api/user-directory/users/<id>/contacts/<c> Update contact
  DELETE /api/user-directory/users/<id>/contacts/<c> Delete contact
  GET    /api/user-directory/users/<id>/tags     Get tags
  POST   /api/user-directory/users/<id>/tags     Add tag
  DELETE /api/user-directory/users/<id>/tags/<t> Remove tag
  GET    /api/user-directory/users/<id>/audit    Get audit log
  POST   /api/user-directory/users/merge         Merge users
  POST   /api/user-directory/users/<id>/hard-delete GDPR hard delete
  GET    /api/user-directory/groups              List groups
  POST   /api/user-directory/groups              Create group
  GET    /api/user-directory/groups/<id>         Get group detail
  DELETE /api/user-directory/groups/<id>         Delete group
  POST   /api/user-directory/groups/<id>/members   Add member
  DELETE /api/user-directory/groups/<id>/members   Remove member
  GET    /api/user-directory/access-info         Access control info
"""

import os
from flask import Blueprint, render_template, jsonify, request

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))

API_PREFIX = '/api/user-directory'


def _db():
    from models.db import db as _db_instance
    return _db_instance


def _get_agent_id():
    """Extract agent ID from request header for permission checks."""
    return request.headers.get('X-Agent-Id', '').strip() or None


def _json_err(msg, code=400):
    return jsonify({'error': msg}), code


def create_blueprint():
    bp = Blueprint('user-directory', __name__,
                   template_folder=os.path.join(PLUGIN_DIR, 'templates'))

    @bp.route('/admin/users')
    def page():
        return render_template('user-directory.html')

    # ---- Users ----

    @bp.route(f'{API_PREFIX}/users', methods=['GET'])
    def api_list_users():
        query = request.args.get('q', '')
        tags = request.args.get('tags', '')
        group_id = request.args.get('group_id', '')
        limit = request.args.get('limit', 20, type=int)
        offset = request.args.get('offset', 0, type=int)
        tag_list = tags.split(',') if tags else None
        results = _db().search_users(query=query, tags=tag_list,
                                     group_id=group_id or None,
                                     limit=min(limit, 100), offset=offset)
        return jsonify({'users': results, 'count': len(results)})

    @bp.route(f'{API_PREFIX}/users', methods=['POST'])
    def api_create_user():
        data = request.get_json() or {}
        user_id = data.get('id')
        name = data.get('name', '').strip()
        if not name:
            return _json_err('Name is required')
        user = _db().create_user(user_id=user_id, name=name,
                                 notes=data.get('notes', ''),
                                 metadata=data.get('metadata'),
                                 actor_type='api', actor_id=_get_agent_id())
        if not user:
            return _json_err('Failed to create user', 500)
        return jsonify({'user': user}), 201

    @bp.route(f'{API_PREFIX}/users/<user_id>', methods=['GET'])
    def api_get_user(user_id):
        include_deleted = request.args.get('include_deleted', '').lower() in ('1', 'true')
        user = _db().get_user(user_id, include_deleted=include_deleted)
        if not user:
            return _json_err('User not found', 404)
        return jsonify({'user': user})

    @bp.route(f'{API_PREFIX}/users/<user_id>', methods=['PUT'])
    def api_update_user(user_id):
        data = request.get_json() or {}
        allowed = {'name', 'notes', 'metadata', 'avatar_url', 'erp_sync_enabled'}
        updates = {k: v for k, v in data.items() if k in allowed}
        if not updates:
            return _json_err('No valid fields to update')
        ok = _db().update_user(user_id, updates,
                               actor_type='api', actor_id=_get_agent_id())
        if not ok:
            return _json_err('User not found', 404)
        return jsonify({'user': _db().get_user(user_id)})

    @bp.route(f'{API_PREFIX}/users/<user_id>', methods=['DELETE'])
    def api_delete_user(user_id):
        ok = _db().soft_delete_user(user_id,
                                    actor_type='api', actor_id=_get_agent_id())
        if not ok:
            return _json_err('User not found', 404)
        return jsonify({'status': 'deleted'})

    @bp.route(f'{API_PREFIX}/users/<user_id>/block', methods=['POST'])
    def api_block_user(user_id):
        data = request.get_json() or {}
        blocked = data.get('blocked', True)
        reason = data.get('reason', '')
        if blocked:
            ok = _db().block_user(user_id, reason=reason,
                                  actor_type='api', actor_id=_get_agent_id())
        else:
            ok = _db().unblock_user(user_id,
                                    actor_type='api', actor_id=_get_agent_id())
        if not ok:
            return _json_err('User not found or already in requested state', 404)
        return jsonify({'status': 'blocked' if blocked else 'unblocked'})

    @bp.route(f'{API_PREFIX}/users/<user_id>/hard-delete', methods=['POST'])
    def api_hard_delete_user(user_id):
        ok = _db().hard_delete_user(user_id,
                                    actor_type='api', actor_id=_get_agent_id())
        if not ok:
            return _json_err('User not found', 404)
        return jsonify({'status': 'hard_deleted'})

    @bp.route(f'{API_PREFIX}/users/merge', methods=['POST'])
    def api_merge_users():
        data = request.get_json() or {}
        source = data.get('source_id')
        target = data.get('target_id')
        if not source or not target:
            return _json_err('source_id and target_id are required')
        ok = _db().merge_users(source, target,
                               actor_type='api', actor_id=_get_agent_id())
        if not ok:
            return _json_err('Merge failed', 500)
        return jsonify({'status': 'merged', 'target_id': target})

    # ---- Contacts ----

    @bp.route(f'{API_PREFIX}/users/<user_id>/contacts', methods=['GET'])
    def api_list_contacts(user_id):
        include_deleted = request.args.get('include_deleted', '').lower() in ('1', 'true')
        contacts = _db().get_contacts(user_id, include_deleted=include_deleted)
        return jsonify({'contacts': contacts})

    @bp.route(f'{API_PREFIX}/users/<user_id>/contacts', methods=['POST'])
    def api_add_contact(user_id):
        data = request.get_json() or {}
        channel_type = data.get('channel_type', '').strip()
        external_user_id = data.get('external_user_id', '').strip()
        if not channel_type or not external_user_id:
            return _json_err('channel_type and external_user_id are required')
        contact = _db().add_contact(
            user_id, channel_type, external_user_id,
            value=data.get('value', external_user_id),
            channel_id=data.get('channel_id'),
            label=data.get('label', ''),
            is_primary=data.get('is_primary', False),
            sync_source=data.get('sync_source', 'evonic'),
            actor_type='api', actor_id=_get_agent_id())
        if not contact:
            return _json_err('Failed to add contact', 500)
        return jsonify({'contact': contact}), 201

    @bp.route(f'{API_PREFIX}/users/<user_id>/contacts/<int:contact_id>', methods=['PUT'])
    def api_update_contact(user_id, contact_id):
        data = request.get_json() or {}
        ok = _db().update_contact(contact_id, data,
                                  actor_type='api', actor_id=_get_agent_id())
        if not ok:
            return _json_err('Contact not found', 404)
        return jsonify({'contact': _db().get_contact(contact_id)})

    @bp.route(f'{API_PREFIX}/users/<user_id>/contacts/<int:contact_id>', methods=['DELETE'])
    def api_delete_contact(user_id, contact_id):
        ok = _db().soft_delete_contact(contact_id,
                                       actor_type='api', actor_id=_get_agent_id())
        if not ok:
            return _json_err('Contact not found', 404)
        return jsonify({'status': 'deleted'})

    @bp.route(f'{API_PREFIX}/users/<user_id>/contacts/<int:contact_id>/primary', methods=['POST'])
    def api_set_primary_contact(user_id, contact_id):
        ok = _db().set_primary_contact(user_id, contact_id,
                                       actor_type='api', actor_id=_get_agent_id())
        if not ok:
            return _json_err('Contact not found', 404)
        return jsonify({'status': 'primary_set'})

    # ---- Tags ----

    @bp.route(f'{API_PREFIX}/users/<user_id>/tags', methods=['GET'])
    def api_get_tags(user_id):
        tags = _db().get_tags(user_id)
        return jsonify({'tags': tags})

    @bp.route(f'{API_PREFIX}/users/<user_id>/tags', methods=['POST'])
    def api_add_tag(user_id):
        data = request.get_json() or {}
        tag = data.get('tag', '').strip()
        if not tag:
            return _json_err('tag is required')
        _db().add_tag(user_id, tag,
                      actor_type='api', actor_id=_get_agent_id())
        return jsonify({'status': 'tag_added', 'tag': tag})

    @bp.route(f'{API_PREFIX}/users/<user_id>/tags/<tag>', methods=['DELETE'])
    def api_remove_tag(user_id, tag):
        _db().remove_tag(user_id, tag,
                         actor_type='api', actor_id=_get_agent_id())
        return jsonify({'status': 'tag_removed'})

    # ---- Audit Log ----

    @bp.route(f'{API_PREFIX}/users/<user_id>/audit', methods=['GET'])
    def api_audit_log(user_id):
        limit = request.args.get('limit', 50, type=int)
        logs = _db().get_audit_log(user_id, limit=min(limit, 200))
        return jsonify({'audit_log': logs})

    # ---- Groups ----

    @bp.route(f'{API_PREFIX}/groups', methods=['GET'])
    def api_list_groups():
        include_deleted = request.args.get('include_deleted', '').lower() in ('1', 'true')
        groups = _db().list_groups(include_deleted=include_deleted)
        # Enrich with member counts
        enriched = []
        for g in groups:
            u, a = _db().get_group_members(g['id'])
            g['user_count'] = len(u)
            g['agent_count'] = len(a)
            enriched.append(g)
        return jsonify({'groups': enriched})

    @bp.route(f'{API_PREFIX}/groups', methods=['POST'])
    def api_create_group():
        data = request.get_json() or {}
        name = data.get('name', '').strip()
        if not name:
            return _json_err('Group name is required')
        group = _db().create_group(name=name,
                                   description=data.get('description', ''),
                                   group_id=data.get('id'),
                                   created_by=_get_agent_id())
        if not group:
            return _json_err('Failed to create group', 500)
        return jsonify({'group': group}), 201

    @bp.route(f'{API_PREFIX}/groups/<group_id>', methods=['GET'])
    def api_get_group(group_id):
        include_deleted = request.args.get('include_deleted', '').lower() in ('1', 'true')
        group = _db().get_group(group_id, include_deleted=include_deleted)
        if not group:
            return _json_err('Group not found', 404)
        users, agents = _db().get_group_members(group_id)
        group['members'] = {'users': users, 'agents': agents}
        return jsonify({'group': group})

    @bp.route(f'{API_PREFIX}/groups/<group_id>', methods=['DELETE'])
    def api_delete_group(group_id):
        ok = _db().delete_group(group_id)
        if not ok:
            return _json_err('Group not found', 404)
        return jsonify({'status': 'deleted'})

    @bp.route(f'{API_PREFIX}/groups/<group_id>/members', methods=['POST'])
    def api_add_group_member(group_id):
        data = request.get_json() or {}
        member_type = data.get('member_type', '')
        member_id = data.get('member_id', '').strip()
        if member_type not in ('user', 'agent') or not member_id:
            return _json_err('member_type (user/agent) and member_id are required')
        ok = _db().add_group_member(group_id, member_type, member_id)
        if not ok:
            return _json_err('Member already exists or group not found', 409)
        return jsonify({'status': 'added'})

    @bp.route(f'{API_PREFIX}/groups/<group_id>/members', methods=['DELETE'])
    def api_remove_group_member(group_id):
        data = request.get_json() or {}
        member_type = data.get('member_type', '')
        member_id = data.get('member_id', '').strip()
        if member_type not in ('user', 'agent') or not member_id:
            return _json_err('member_type (user/agent) and member_id are required')
        ok = _db().remove_group_member(group_id, member_type, member_id)
        if not ok:
            return _json_err('Member not found', 404)
        return jsonify({'status': 'removed'})

    # ---- Access Control ----

    @bp.route(f'{API_PREFIX}/access-info', methods=['GET'])
    def api_access_info():
        agent_id = request.args.get('agent_id', _get_agent_id())
        user_id = request.args.get('user_id', '')
        if not agent_id or not user_id:
            return _json_err('agent_id and user_id are required')
        info = _db().get_access_control_info(agent_id, user_id)
        return jsonify({'access_info': info})

    # ---- Tag Rules ----

    @bp.route(f'{API_PREFIX}/tag-rules', methods=['GET'])
    def api_list_tag_rules():
        enabled_only = request.args.get('enabled_only', '').lower() in ('1', 'true')
        rules = _db().get_tag_rules(enabled_only=enabled_only)
        return jsonify({'rules': rules})

    @bp.route(f'{API_PREFIX}/tag-rules', methods=['POST'])
    def api_create_tag_rule():
        data = request.get_json() or {}
        rule_id = data.get('id')
        tag_pattern = data.get('tag_pattern')
        effect = data.get('effect')
        if not rule_id or not tag_pattern or not effect:
            return _json_err('id, tag_pattern, and effect are required')
        priority = data.get('priority', 5)
        config = data.get('config', {})
        description = data.get('description', '')
        try:
            rule = _db().create_tag_rule(rule_id, tag_pattern, effect,
                                         priority=priority, config=config,
                                         description=description)
        except ValueError as e:
            return _json_err(str(e))
        if not rule:
            return _json_err('Failed to create tag rule', 500)
        return jsonify({'rule': rule}), 201

    @bp.route(f'{API_PREFIX}/tag-rules/<rule_id>', methods=['GET'])
    def api_get_tag_rule(rule_id):
        rule = _db().get_tag_rule(rule_id)
        if not rule:
            return _json_err('Tag rule not found', 404)
        return jsonify({'rule': rule})

    @bp.route(f'{API_PREFIX}/tag-rules/<rule_id>', methods=['PUT'])
    def api_update_tag_rule(rule_id):
        data = request.get_json() or {}
        try:
            rule = _db().update_tag_rule(rule_id, data)
        except ValueError as e:
            return _json_err(str(e))
        if not rule:
            return _json_err('Tag rule not found', 404)
        return jsonify({'rule': rule})

    @bp.route(f'{API_PREFIX}/tag-rules/<rule_id>', methods=['DELETE'])
    def api_delete_tag_rule(rule_id):
        ok = _db().delete_tag_rule(rule_id)
        if not ok:
            return _json_err('Tag rule not found', 404)
        return jsonify({'status': 'deleted'})

    @bp.route(f'{API_PREFIX}/tag-rules/<rule_id>/toggle', methods=['PUT'])
    def api_toggle_tag_rule(rule_id):
        rule = _db().toggle_tag_rule(rule_id)
        if not rule:
            return _json_err('Tag rule not found', 404)
        return jsonify({'rule': rule, 'enabled': rule['enabled']})

    @bp.route(f'{API_PREFIX}/check-access', methods=['POST'])
    def api_check_access():
        """Debug endpoint to evaluate access control for a given agent+user pair."""
        data = request.get_json() or {}
        agent_id = data.get('agent_id', _get_agent_id())
        user_id = data.get('user_id', '')
        if not agent_id or not user_id:
            return _json_err('agent_id and user_id are required')
        info = _db().get_access_control_info(agent_id, user_id)
        return jsonify({'access_info': info})

    return bp
