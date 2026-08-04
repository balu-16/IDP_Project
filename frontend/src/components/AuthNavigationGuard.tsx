import { useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '@/components/auth/AuthContext';

const PUBLIC_PATHS = new Set(['/', '/login', '/signup']);
const PROTECTED_PATH_PREFIXES = ['/chat', '/settings'];

const AuthNavigationGuard: React.FC = () => {
  const { user, loading } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    if (loading) {
      return;
    }

    const currentPath = location.pathname;
    const isPublicPath = PUBLIC_PATHS.has(currentPath);
    const isProtectedPath = PROTECTED_PATH_PREFIXES.some((prefix) =>
      currentPath === prefix || currentPath.startsWith(`${prefix}/`)
    );

    if (user && isPublicPath) {
      navigate('/chat', { replace: true });
      return;
    }

    if (!user && isProtectedPath) {
      navigate('/login', { replace: true });
    }
  }, [loading, location.pathname, navigate, user]);

  return null;
};

export default AuthNavigationGuard;
