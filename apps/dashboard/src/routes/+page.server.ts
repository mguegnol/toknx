import { getMockDashboardSnapshot } from '$lib/mock-dashboard';
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
const MOCK_MODE = ['1', 'true', 'yes', 'on'].includes(
	(process.env.TOKNX_DASHBOARD_MOCK_MODE ?? '').toLowerCase()
);

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
	if (MOCK_MODE) {
		const mock = getMockDashboardSnapshot();
		return {
			publicApiBase: PUBLIC_API_BASE,
			mockMode: true,
			stats: mock.stats,
			models: mock.models,
			leaders: mock.leaders,
			initialEvents: mock.events
		};
	}

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
		mockMode: false,
		stats,
		models: models.models,
		leaders: leaderboard.leaders,
		initialEvents: []
	};
}
