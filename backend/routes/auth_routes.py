"""Profile routes. Authentication and password recovery are handled by Supabase Auth."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from services.database import DatabaseService, Identity, get_database_service, get_identity, require_matching_user

router = APIRouter(prefix='/api/auth', tags=['authentication'])


class ProfileUpdate(BaseModel):
    """Display-name/phone update only. Email changes are read-only in the demo."""
    model_config = ConfigDict(extra='forbid')
    full_name: str | None = Field(default=None, min_length=1, max_length=100)
    phone_number: str | None = Field(default=None, max_length=20)


@router.post('/login')
@router.post('/register')
async def legacy_auth_disabled():
    raise HTTPException(410, 'Use Supabase Auth; legacy passwords and tokens are disabled')


@router.get('/me')
async def me(identity: Identity = Depends(get_identity)):
    return {'success': True, 'user': identity.profile}


@router.put('/user/{user_id}')
async def update_profile(user_id: int, body: ProfileUpdate,
                         identity: Identity = Depends(get_identity),
                         database: DatabaseService = Depends(get_database_service)):
    require_matching_user(identity, user_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get('full_name') is not None:
        changes['full_name'] = changes['full_name'].strip()
        if not changes['full_name']:
            raise HTTPException(422, 'Full name cannot be blank')
    if 'full_name' in changes and changes['full_name'] is None:
        raise HTTPException(422, 'Full name cannot be null')
    profile_data = identity.profile
    if changes:
        rows = await database.request('PATCH', '/rest/v1/signup_users',
            params={'id': f'eq.{identity.user_id}', 'select': 'id,auth_user_id,full_name,email,phone_number,created_at'},
            json=changes, headers={'Prefer': 'return=representation'})
        if not rows:
            raise HTTPException(409, 'Profile update did not persist')
        profile_data = rows[0]
    return {'success': True, 'user': profile_data}
