import structlog
import time
import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from functools import wraps
from collections import defaultdict, deque
import json
from database import AsyncSessionLocal, User
from sqlalchemy import select, func, text, case

logger = structlog.get_logger()

class PerformanceMetrics:
    """Real-time performance metrics collection"""
    
    def __init__(self):
        self.metrics = defaultdict(lambda: {
            'count': 0,
            'total_time': 0,
            'avg_time': 0,
            'min_time': float('inf'),
            'max_time': 0,
            'recent_times': deque(maxlen=100),  # Keep last 100 measurements
            'errors': 0,
            'success_rate': 0
        })
        self.sync_stats = defaultdict(lambda: {
            'gmail_syncs': 0,
            'calendar_syncs': 0,
            'hubspot_syncs': 0,
            'total_syncs': 0,
            'failed_syncs': 0,
            'avg_sync_time': 0,
            'last_sync': None
        })
    
    def record_operation(self, operation_name: str, duration: float, success: bool = True):
        """Record performance metrics for an operation"""
        metric = self.metrics[operation_name]
        
        metric['count'] += 1
        metric['total_time'] += duration
        metric['avg_time'] = metric['total_time'] / metric['count']
        metric['min_time'] = min(metric['min_time'], duration)
        metric['max_time'] = max(metric['max_time'], duration)
        metric['recent_times'].append(duration)
        
        if not success:
            metric['errors'] += 1
        
        metric['success_rate'] = ((metric['count'] - metric['errors']) / metric['count']) * 100
    
    def record_sync(self, user_id: str, service: str, duration: float, success: bool = True):
        """Record sync-specific metrics"""
        stats = self.sync_stats[user_id]
        
        if service in ['gmail', 'calendar', 'hubspot']:
            stats[f'{service}_syncs'] += 1
        
        stats['total_syncs'] += 1
        if not success:
            stats['failed_syncs'] += 1
        
        # Update average sync time
        total_time = stats.get('total_sync_time', 0) + duration
        stats['total_sync_time'] = total_time
        stats['avg_sync_time'] = total_time / stats['total_syncs']
        stats['last_sync'] = datetime.utcnow().isoformat()
    
    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get performance metrics summary"""
        summary = {
            'timestamp': datetime.utcnow().isoformat(),
            'operations': {},
            'system_health': self._calculate_system_health()
        }
        
        for op_name, metric in self.metrics.items():
            summary['operations'][op_name] = {
                'count': metric['count'],
                'avg_time_ms': round(metric['avg_time'] * 1000, 2),
                'min_time_ms': round(metric['min_time'] * 1000, 2) if metric['min_time'] != float('inf') else 0,
                'max_time_ms': round(metric['max_time'] * 1000, 2),
                'success_rate': round(metric['success_rate'], 2),
                'recent_avg_ms': round(sum(metric['recent_times']) / len(metric['recent_times']) * 1000, 2) if metric['recent_times'] else 0
            }
        
        return summary
    
    def _calculate_system_health(self) -> str:
        """Calculate overall system health based on metrics"""
        if not self.metrics:
            return "unknown"
        
        total_operations = sum(m['count'] for m in self.metrics.values())
        total_errors = sum(m['errors'] for m in self.metrics.values())
        
        if total_operations == 0:
            return "unknown"
        
        error_rate = (total_errors / total_operations) * 100
        avg_response_time = sum(m['avg_time'] for m in self.metrics.values()) / len(self.metrics)
        
        if error_rate > 10 or avg_response_time > 5:
            return "degraded"
        elif error_rate > 5 or avg_response_time > 2:
            return "warning"
        else:
            return "healthy"

class SimpleCache:
    """Simple in-memory cache with TTL"""
    
    def __init__(self):
        self.cache = {}
        self.timestamps = {}
        self.hits = 0
        self.misses = 0
    
    def get(self, key: str, ttl_seconds: int = 300) -> Optional[Any]:
        """Get cached value if not expired"""
        if key in self.cache:
            if time.time() - self.timestamps[key] < ttl_seconds:
                self.hits += 1
                return self.cache[key]
            else:
                # Expired, remove from cache
                del self.cache[key]
                del self.timestamps[key]
        
        self.misses += 1
        return None
    
    def set(self, key: str, value: Any):
        """Set cached value"""
        self.cache[key] = value
        self.timestamps[key] = time.time()
    
    def clear_expired(self, ttl_seconds: int = 300):
        """Clear expired cache entries"""
        current_time = time.time()
        expired_keys = [
            key for key, timestamp in self.timestamps.items()
            if current_time - timestamp >= ttl_seconds
        ]
        
        for key in expired_keys:
            del self.cache[key]
            del self.timestamps[key]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        total_requests = self.hits + self.misses
        hit_rate = (self.hits / total_requests * 100) if total_requests > 0 else 0
        
        return {
            'hits': self.hits,
            'misses': self.misses,
            'hit_rate': round(hit_rate, 2),
            'cached_items': len(self.cache)
        }

class PerformanceMonitor:
    """Central performance monitoring and optimization"""
    
    def __init__(self):
        self.metrics = PerformanceMetrics()
        self.cache = SimpleCache()
        self.start_time = datetime.utcnow()
        
    def timed_operation(self, operation_name: str):
        """Decorator to time operations and record metrics"""
        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                start_time = time.time()
                success = True
                
                try:
                    result = await func(*args, **kwargs)
                    return result
                except Exception as e:
                    success = False
                    raise e
                finally:
                    duration = time.time() - start_time
                    self.metrics.record_operation(operation_name, duration, success)
                    
                    if duration > 2:  # Log slow operations
                        logger.warning(f"Slow operation detected: {operation_name} took {duration:.2f}s")
            
            return wrapper
        return decorator
    
    def timed_sync(self, user_id: str, service: str):
        """Decorator to time sync operations"""
        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                start_time = time.time()
                success = True
                
                try:
                    result = await func(*args, **kwargs)
                    return result
                except Exception as e:
                    success = False
                    raise e
                finally:
                    duration = time.time() - start_time
                    self.metrics.record_sync(user_id, service, duration, success)
                    
                    logger.info(f"Sync completed: {service} for user {user_id} in {duration:.2f}s (success: {success})")
            
            return wrapper
        return decorator
    
    async def get_database_stats(self) -> Dict[str, Any]:
        """Get database performance statistics"""
        try:
            async with AsyncSessionLocal() as session:
                # Get table sizes
                table_stats = {}
                
                tables = ['users', 'emails', 'hubspot_contacts', 'hubspot_deals', 'hubspot_companies', 'calendar_events']
                
                for table in tables:
                    result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
                    count = result.scalar()
                    table_stats[table] = count
                
                # Get recent activity
                activity_result = await session.execute(
                    select(
                        func.count(User.id).label("total_users"),
                        func.sum(
                            case(
                                (User.google_access_token.isnot(None), 1),
                                else_=0
                            )
                        ).label("google_users"),
                        func.sum(
                            case(
                                (User.hubspot_access_token.isnot(None), 1),
                                else_=0
                            )
                        ).label("hubspot_users")
                    )
                )
                activity_stats = activity_result.first()
                
                return {
                    'table_sizes': table_stats,
                    'user_stats': {
                        'total_users': activity_stats.total_users or 0,
                        'google_connected': activity_stats.google_users or 0,
                        'hubspot_connected': activity_stats.hubspot_users or 0
                    },
                    'timestamp': datetime.utcnow().isoformat()
                }
                
        except Exception as e:
            logger.error(f"Failed to get database stats: {str(e)}")
            return {"error": str(e)}
    
    async def get_system_status(self) -> Dict[str, Any]:
        """Get comprehensive system status"""
        uptime = datetime.utcnow() - self.start_time
        
        return {
            'timestamp': datetime.utcnow().isoformat(),
            'uptime_seconds': uptime.total_seconds(),
            'uptime_human': str(uptime).split('.')[0],  # Remove microseconds
            'performance_metrics': self.metrics.get_metrics_summary(),
            'cache_stats': self.cache.get_stats(),
            'database_stats': await self.get_database_stats(),
            'system_health': self.metrics._calculate_system_health()
        }
    
    def optimize_cache_key(self, user_id: str, operation: str, **params) -> str:
        """Generate optimized cache key"""
        key_parts = [user_id, operation]
        
        # Add sorted parameters for consistent keys
        if params:
            sorted_params = sorted(params.items())
            param_str = '&'.join([f"{k}={v}" for k, v in sorted_params])
            key_parts.append(param_str)
        
        return ':'.join(key_parts)
    
    async def cached_health_check(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get cached health check result"""
        cache_key = self.optimize_cache_key(user_id, "health_check")
        return self.cache.get(cache_key, ttl_seconds=300)  # 5 minute cache
    
    def cache_health_check(self, user_id: str, result: Dict[str, Any]):
        """Cache health check result"""
        cache_key = self.optimize_cache_key(user_id, "health_check")
        self.cache.set(cache_key, result)
    
    async def get_performance_recommendations(self) -> List[str]:
        """Get performance improvement recommendations"""
        recommendations = []
        
        # Check cache hit rate
        cache_stats = self.cache.get_stats()
        if cache_stats['hit_rate'] < 50 and cache_stats['hits'] + cache_stats['misses'] > 100:
            recommendations.append("Low cache hit rate detected. Consider increasing cache TTL or optimizing cache keys")
        
        # Check operation performance
        metrics_summary = self.metrics.get_metrics_summary()
        for op_name, metrics in metrics_summary['operations'].items():
            if metrics['avg_time_ms'] > 2000:
                recommendations.append(f"Operation '{op_name}' is slow (avg: {metrics['avg_time_ms']}ms). Consider optimization")
            
            if metrics['success_rate'] < 95:
                recommendations.append(f"Operation '{op_name}' has low success rate ({metrics['success_rate']}%). Check error handling")
        
        # Check system health
        if metrics_summary['system_health'] != 'healthy':
            recommendations.append(f"System health is {metrics_summary['system_health']}. Monitor performance closely")
        
        return recommendations
    
    def cleanup(self):
        """Cleanup expired cache entries and old metrics"""
        self.cache.clear_expired()
        
        # Reset metrics if they get too large (keep only recent data)
        for metric in self.metrics.metrics.values():
            if len(metric['recent_times']) >= 100:
                # Keep metrics but reset counters for fresh start
                metric['recent_times'].clear()

# Global instance
performance_monitor = PerformanceMonitor() 