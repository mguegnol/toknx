import type { Leader, ModelRow, Stats } from '$lib/types';

const API_BASE = (
	process.env.TOKNX_PUBLIC_API_BASE ??
	process.env.VITE_TOKNX_API_BASE ??
	'http://coordinator:8000'
).replace(/\/$/, '');
const PUBLIC_API_BASE = (
	process.env.VITE_TOKNX_API_BASE ??
	process.env.TOKNX_PUBLIC_BASE_URL ??
	'http://localhost/api'
).replace(/\/$/, '');

async function loadJson<T>(path: string, fallback: T): Promise<T> {
	try {
		const response = await fetch(`${API_BASE}${path}`, { cache: 'no-store' });
		if (!response.ok) {
			return fallback;
		}
		return (await response.json()) as T;
	} catch {
		return fallback;
	}
}

export async function load() {
	const stats = await loadJson<Stats>('/stats', {
		nodes_online: 0,
		jobs_running: 0,
		tokens_total: 0,
		tokens_per_second: 0
	});
	const models = await loadJson<{ models: ModelRow[] }>('/v1/models', { models: [] });
	const leaderboard = await loadJson<{ leaders: Leader[] }>('/leaderboard', { leaders: [] });

	return {
		publicApiBase: PUBLIC_API_BASE,
		stats,
		models: models.models,
		leaders: leaderboard.leaders
	};
}
