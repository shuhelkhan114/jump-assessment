interface FetchOptions extends RequestInit {
    requiresAuth?: boolean;
}

export const fetchWithAuth = async (url: string, options: FetchOptions = {}) => {
    const token = localStorage.getItem('token');
    const { requiresAuth = true, headers = {}, ...rest } = options;

    const finalHeaders: Record<string, string> = {
        ...headers as Record<string, string>,
    };

    if (requiresAuth && token) {
        finalHeaders['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(url, {
        headers: finalHeaders,
        ...rest,
    });

    if (response.status === 401) {
        // Handle unauthorized error
        localStorage.removeItem('token');
        window.location.href = '/login';
        throw new Error('Unauthorized');
    }

    return response;
}; 