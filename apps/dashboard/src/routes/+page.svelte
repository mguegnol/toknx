<script lang="ts">
	import { onMount } from 'svelte';
	import type { EventRow, Leader, ModelRow, Stats } from '$lib/types';

	export let data: {
		publicApiBase: string;
		stats: Stats;
		models: ModelRow[];
		leaders: Leader[];
	};

	const API_BASE = data.publicApiBase.replace(/\/$/, '');
	const POLL_INTERVAL_MS = 5000;
	const SSE_RECONNECT_DELAY_MS = 2000;
	const EMPTY_STATS: Stats = {
		nodes_online: 0,
		jobs_running: 0,
		tokens_total: 0,
		tokens_per_second: 0
	};

	let stats = data.stats;
	let models = data.models;
	let leaders = data.leaders;
	let events: EventRow[] = [];
	let copied = false;
	let refreshTimer: ReturnType<typeof setInterval> | undefined;
	let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
	let source: EventSource | undefined;

	const INSTALL_CMD = 'curl -fsSL https://toknx.co/install-node.sh | bash';

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

	async function refreshDashboardData() {
		const [nextStats, nextModels, nextLeaders] = await Promise.all([
			loadJson<Stats>('/stats', stats ?? EMPTY_STATS),
			loadJson<{ models: ModelRow[] }>('/v1/models', { models }),
			loadJson<{ leaders: Leader[] }>('/leaderboard', { leaders })
		]);
		stats = nextStats;
		models = nextModels.models;
		leaders = nextLeaders.leaders;
	}

	function copyInstall() {
		navigator.clipboard.writeText(INSTALL_CMD).then(() => {
			copied = true;
			setTimeout(() => (copied = false), 2000);
		});
	}

	function closeEventSource() {
		source?.close();
		source = undefined;
	}

	function connectEventStream() {
		if (reconnectTimer) {
			clearTimeout(reconnectTimer);
			reconnectTimer = undefined;
		}
		closeEventSource();
		source = new EventSource(`${API_BASE}/events/stream`);
		source.onmessage = (event) => {
			const parsed = JSON.parse(event.data) as EventRow;
			events = [parsed, ...events].slice(0, 24);
		};
		source.onerror = () => {
			closeEventSource();
			if (reconnectTimer) {
				clearTimeout(reconnectTimer);
			}
			reconnectTimer = setTimeout(() => {
				connectEventStream();
			}, SSE_RECONNECT_DELAY_MS);
		};
	}

	function stopPolling() {
		if (refreshTimer) {
			clearInterval(refreshTimer);
			refreshTimer = undefined;
		}
	}

	function startPolling() {
		stopPolling();
		void refreshDashboardData();
		refreshTimer = setInterval(() => {
			if (document.visibilityState === 'visible') {
				void refreshDashboardData();
			}
		}, POLL_INTERVAL_MS);
	}

	function eventSummary(event: EventRow) {
		if (event.models?.length) return event.models.join(', ');
		if (event.model && event.type === 'job_completed' && event.output_tokens !== undefined) {
			return `${event.model} • ${event.output_tokens} tok`;
		}
		if (event.model && event.error) return `${event.model} • ${event.error}`;
		if (event.model) return event.model;
		if (event.hardware?.chip) return event.hardware.chip;
		return 'network event';
	}

	onMount(() => {
		const handleVisibilityChange = () => {
			if (document.visibilityState === 'hidden') {
				stopPolling();
				return;
			}
			connectEventStream();
			startPolling();
		};

		connectEventStream();
		startPolling();
		document.addEventListener('visibilitychange', handleVisibilityChange);

		return () => {
			document.removeEventListener('visibilitychange', handleVisibilityChange);
			stopPolling();
			closeEventSource();
			if (reconnectTimer) {
				clearTimeout(reconnectTimer);
			}
		};
	});

	const rankLabel = (i: number) => ['1st', '2nd', '3rd'][i] ?? `${i + 1}th`;
	const rankClass = (i: number) => ['gold', 'silver', 'bronze'][i] ?? '';

	function eventColor(type: string) {
		if (type.includes('job')) return 'ev-job';
		if (type.includes('node')) return 'ev-node';
		if (type.includes('token')) return 'ev-token';
		return 'ev-default';
	}
</script>

<svelte:head>
	<title>toknX</title>
	<meta
		name="description"
		content="Contribute idle Apple Silicon hardware. Earn LLM tokens. toknX is a compute co-op for inference."
	/>
</svelte:head>

<div class="shell">
	<section class="hero">
		<p class="eyebrow"><span class="dot"></span>toknX</p>
		<h1>Distributed inference network for Apple Silicon.</h1>
		<p class="lede">
			Turn unused Mac compute into tokens you can spend across the network.
		</p>
		<div class="join">
			<p class="join-label">Join the network</p>
			<div class="install-row">
				<code class="install-cmd">{INSTALL_CMD}</code>
				<button class="copy-btn" on:click={copyInstall} aria-label="Copy install command">
					{#if copied}
						<span class="copy-icon">✓</span>
					{:else}
						<span class="copy-icon">⎘</span>
					{/if}
				</button>
			</div>
			<a href="https://github.com/mguegnol/toknx" class="gh-btn" target="_blank" rel="noopener">
				<svg class="gh-logo" viewBox="0 0 16 16" aria-hidden="true" fill="currentColor">
					<path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38
					0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13
					-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66
					.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15
					-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09
					2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82
					2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01
					2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/>
				</svg>
				View on GitHub
			</a>
		</div>
	</section>

	<section class="stats-grid">
		<article>
			<span class="stat-label">Nodes online</span>
			<strong>{stats.nodes_online}</strong>
		</article>
		<article>
			<span class="stat-label">Jobs running</span>
			<strong>{stats.jobs_running}</strong>
		</article>
		<article>
			<span class="stat-label">Tokens generated</span>
			<strong>{stats.tokens_total.toLocaleString()}</strong>
		</article>
		<article>
			<span class="stat-label">Network throughput</span>
			<strong>{stats.tokens_per_second} <small>tok/s</small></strong>
		</article>
	</section>

	<div class="content-grid">
		<section class="panel">
			<div class="panel-header">
				<div class="panel-title-row">
					<h2>Models available now</h2>
				</div>
				<p class="panel-sub"><span class="bullet"></span>Live inventory from online contributor nodes.</p>
			</div>
			<div class="rows">
				{#if models.length}
					{#each models as model}
						<div class="row">
							<div class="row-info">
								<strong>{model.hf_id}</strong>
								<span>{model.estimated_ram_gb} GB RAM</span>
							</div>
							<div class="row-meta">
								<span class="tag">{model.node_count} nodes</span>
								<span class="tag">Tier {model.pricing_tier}</span>
								<span class="tag accent-tag">{model.credits_per_1k_tokens} cr / 1K</span>
							</div>
						</div>
					{/each}
				{:else}
					<p class="empty">No nodes are online yet.</p>
				{/if}
			</div>
		</section>

		<section class="panel">
			<div class="panel-header">
				<div class="panel-title-row">
					<h2>Live activity</h2>
					<span class="live-badge"><span class="live-dot"></span>Live</span>
				</div>
				<p class="panel-sub"><span class="bullet"></span>Streaming network events over SSE.</p>
			</div>
			<div class="rows activity">
				{#if events.length}
					{#each events as event}
						<div class="event-row">
							<time>{new Date(event.created_at).toLocaleTimeString()}</time>
							<div class="event-body">
								<strong class={eventColor(event.type)}>{event.type.replace('_', ' ')}</strong>
								<span>{eventSummary(event)}</span>
							</div>
						</div>
					{/each}
				{:else}
					<p class="empty">Waiting for the first event.</p>
				{/if}
			</div>
		</section>
	</div>

	<section class="panel leaderboard">
		<div class="panel-header">
			<div class="panel-title-row">
				<h2>Top contributors <span class="period-badge">7d</span></h2>
			</div>
			<p class="panel-sub"><span class="bullet"></span>Credits earned from completed jobs.</p>
		</div>
		<div class="rows">
			{#if leaders.length}
				{#each leaders as leader, index}
					<div class="row">
						<div class="row-info">
							<div class="leader-name">
								<span class="rank {rankClass(index)}">{rankLabel(index)}</span>
								<strong>@{leader.github_username}</strong>
							</div>
							<span>Contributor</span>
						</div>
						<div class="row-meta">
							<span class="tag accent-tag">{leader.credits_earned} credits</span>
						</div>
					</div>
				{/each}
			{:else}
				<p class="empty">Leaderboard fills as jobs complete.</p>
			{/if}
		</div>
	</section>
</div>

<style>
	:global(html) {
		background: #020b1d;
	}

	:global(body) {
		--bg: #020b1d;
		--panel: rgba(8, 18, 42, 0.9);
		--panel-border: rgba(255, 255, 255, 0.07);
		--panel-border-hover: rgba(255, 255, 255, 0.13);
		--line: rgba(255, 255, 255, 0.07);
		--text: #f0eee9;
		--muted: #8b93a8;
		--muted-soft: #636b7e;
		--accent: #f26a21;
		--accent-dim: rgba(242, 106, 33, 0.15);
		--accent-glow: rgba(242, 106, 33, 0.25);
		margin: 0;
		font-family: 'Avenir Next', 'Segoe UI', 'Helvetica Neue', sans-serif;
		background: #020b1d;
		color: var(--text);
		-webkit-font-smoothing: antialiased;
	}

	:global(body)::before {
		content: '';
		position: fixed;
		inset: 0;
		pointer-events: none;
		background:
			radial-gradient(ellipse 80% 40% at 50% -10%, rgba(30, 58, 110, 0.35) 0%, transparent 70%),
			radial-gradient(ellipse 40% 30% at 80% 60%, rgba(242, 106, 33, 0.04) 0%, transparent 60%);
		z-index: 0;
	}

	:global(*) {
		box-sizing: border-box;
	}

	.shell {
		position: relative;
		max-width: 1200px;
		margin: 0 auto;
		padding: 40px 28px 96px;
		z-index: 1;
	}

	/* ── Hero ─────────────────────────────────── */

	.hero {
		padding: 44px 40px 40px;
		background: var(--panel);
		border: 1px solid var(--panel-border);
		border-radius: 16px;
		position: relative;
		overflow: hidden;
		text-align: center;
		display: flex;
		flex-direction: column;
		align-items: center;
	}

	.hero::after {
		content: '';
		position: absolute;
		top: 0;
		left: 0;
		right: 0;
		height: 1px;
		background: linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.12) 40%, rgba(255,255,255,0.12) 60%, transparent 100%);
	}

	.eyebrow {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		margin: 0;
		text-transform: uppercase;
		letter-spacing: 0.2em;
		font-size: 0.72rem;
		font-weight: 600;
		color: var(--muted);
	}

	.dot {
		width: 7px;
		height: 7px;
		border-radius: 50%;
		background: var(--accent);
		box-shadow: 0 0 8px var(--accent-glow);
		flex-shrink: 0;
	}

	h1 {
		font-family: 'Iowan Old Style', 'Palatino Linotype', 'Book Antiqua', 'Times New Roman', serif;
		font-weight: 400;
		letter-spacing: -0.035em;
		max-width: 20ch;
		margin: 2.5rem 0 1rem;
		font-size: clamp(3rem, 5.5vw, 5.8rem);
		line-height: 0.9;
		text-wrap: balance;
	}

	.lede {
		max-width: 48rem;
		margin: 0;
		font-size: clamp(1rem, 1.3vw, 1.18rem);
		line-height: 1.6;
		color: #a8b0c2;
	}

	.join {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 14px;
		margin-top: 36px;
	}

	.join-label {
		margin: 0;
		text-transform: uppercase;
		letter-spacing: 0.18em;
		font-size: 0.72rem;
		font-weight: 600;
		color: var(--muted);
	}

	.install-row {
		display: flex;
		align-items: center;
		gap: 0;
		background: rgba(0, 0, 0, 0.35);
		border: 1px solid var(--panel-border-hover);
		border-radius: 10px;
		overflow: hidden;
		max-width: 100%;
	}

	.install-cmd {
		flex: 1;
		padding: 12px 18px;
		font-family: 'SF Mono', 'Fira Mono', 'Cascadia Code', monospace;
		font-size: 0.88rem;
		color: #c8d8f0;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		user-select: all;
	}

	.copy-btn {
		flex-shrink: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		width: 44px;
		height: 44px;
		background: rgba(255, 255, 255, 0.05);
		border: none;
		border-left: 1px solid var(--panel-border-hover);
		color: var(--muted);
		cursor: pointer;
		transition: background 140ms ease, color 140ms ease;
	}

	.copy-btn:hover {
		background: rgba(255, 255, 255, 0.1);
		color: #e8ecf4;
	}

	.copy-icon {
		font-size: 1rem;
		line-height: 1;
	}

	.gh-btn {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		padding: 0 20px;
		min-height: 42px;
		border-radius: 10px;
		background: rgba(255, 255, 255, 0.04);
		border: 1px solid var(--panel-border-hover);
		color: #c8cedd;
		text-decoration: none;
		font-size: 0.9rem;
		font-weight: 500;
		transition: background 160ms ease, border-color 160ms ease, transform 160ms ease;
	}

	.gh-btn:hover {
		background: rgba(255, 255, 255, 0.08);
		border-color: rgba(255, 255, 255, 0.18);
		transform: translateY(-1px);
	}

	.gh-logo {
		width: 18px;
		height: 18px;
		flex-shrink: 0;
	}

	/* ── Stats ────────────────────────────────── */

	.stats-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
		gap: 12px;
		margin-top: 12px;
	}

	.stats-grid article {
		padding: 20px 22px 22px;
		background: var(--panel);
		border: 1px solid var(--panel-border);
		border-radius: 14px;
		border-top: 2px solid rgba(255, 255, 255, 0.08);
		position: relative;
		overflow: hidden;
		transition: border-color 180ms ease;
	}

	.stats-grid article:hover {
		border-color: var(--panel-border-hover);
	}

	.stat-label {
		display: block;
		font-size: 0.72rem;
		text-transform: uppercase;
		letter-spacing: 0.16em;
		color: var(--muted);
		font-weight: 500;
		margin-bottom: 12px;
	}

	.stats-grid strong {
		display: block;
		font-family: 'Iowan Old Style', 'Palatino Linotype', 'Book Antiqua', 'Times New Roman', serif;
		font-weight: 400;
		font-size: clamp(2rem, 2.5vw, 2.8rem);
		line-height: 0.95;
		letter-spacing: -0.03em;
		color: #eef1f8;
	}

	.stats-grid strong small {
		font-size: 0.55em;
		color: var(--muted);
		letter-spacing: 0;
	}

	/* ── Content grid ─────────────────────────── */

	.content-grid {
		display: grid;
		grid-template-columns: 1.2fr 0.8fr;
		gap: 12px;
		margin-top: 12px;
	}

	/* ── Panels ───────────────────────────────── */

	.panel {
		background: var(--panel);
		border: 1px solid var(--panel-border);
		border-radius: 14px;
		padding: 26px 24px 24px;
		position: relative;
		overflow: hidden;
	}

	.panel::before {
		content: '';
		position: absolute;
		top: 0;
		left: 0;
		right: 0;
		height: 1px;
		background: linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.1) 50%, transparent 100%);
	}

	.panel-header {
		margin-bottom: 18px;
	}

	.panel-title-row {
		display: flex;
		align-items: flex-start;
		gap: 12px;
	}

	h2 {
		font-family: 'Iowan Old Style', 'Palatino Linotype', 'Book Antiqua', 'Times New Roman', serif;
		font-weight: 400;
		letter-spacing: -0.03em;
		margin: 0 0 8px;
		font-size: clamp(1.7rem, 2.2vw, 2.6rem);
		line-height: 0.92;
		text-wrap: balance;
	}

	.period-badge {
		display: inline-flex;
		align-items: center;
		padding: 3px 9px;
		background: var(--accent-dim);
		border: 1px solid rgba(242, 106, 33, 0.3);
		border-radius: 6px;
		font-family: 'Avenir Next', 'Segoe UI', sans-serif;
		font-size: 0.72rem;
		font-weight: 600;
		letter-spacing: 0.06em;
		color: var(--accent);
		vertical-align: middle;
		margin-left: 4px;
		margin-bottom: 2px;
	}

	.live-badge {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 4px 10px;
		background: rgba(34, 197, 94, 0.1);
		border: 1px solid rgba(34, 197, 94, 0.25);
		border-radius: 999px;
		font-size: 0.72rem;
		font-weight: 600;
		letter-spacing: 0.08em;
		color: #4ade80;
		white-space: nowrap;
		margin-top: 4px;
	}

	.live-dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: #4ade80;
		animation: pulse 2s ease-in-out infinite;
	}

	@keyframes pulse {
		0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(74, 222, 128, 0.5); }
		50% { opacity: 0.7; box-shadow: 0 0 0 4px rgba(74, 222, 128, 0); }
	}

	.panel-sub {
		display: flex;
		align-items: center;
		gap: 8px;
		margin: 0;
		font-size: 0.78rem;
		color: var(--muted-soft);
		text-transform: uppercase;
		letter-spacing: 0.13em;
	}

	.bullet {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--accent);
		flex-shrink: 0;
	}

	/* ── Rows ─────────────────────────────────── */

	.rows {
		display: flex;
		flex-direction: column;
	}

	.row,
	.event-row {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 10px;
		padding: 12px 0;
		border-top: 1px solid var(--line);
		transition: background 140ms ease;
	}

	.row:first-child,
	.event-row:first-child {
		border-top: none;
		padding-top: 0;
	}

	.row-info {
		display: flex;
		flex-direction: column;
		gap: 3px;
		min-width: 0;
	}

	.row-info strong {
		font-family: 'Avenir Next', 'Segoe UI', sans-serif;
		font-size: 0.95rem;
		font-weight: 500;
		color: #e8ecf4;
		letter-spacing: -0.01em;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.row-info span,
	.event-row span {
		font-size: 0.83rem;
		color: var(--muted);
		line-height: 1.4;
	}

	.row-meta {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		justify-content: flex-end;
		flex-shrink: 0;
	}

	.tag {
		display: inline-flex;
		align-items: center;
		min-height: 28px;
		padding: 0 10px;
		border: 1px solid var(--panel-border-hover);
		border-radius: 7px;
		background: rgba(255, 255, 255, 0.03);
		font-size: 0.8rem;
		color: #bec7d8;
		white-space: nowrap;
	}

	.accent-tag {
		background: var(--accent-dim);
		border-color: rgba(242, 106, 33, 0.28);
		color: #f59555;
	}

	/* ── Live activity ────────────────────────── */

	.activity {
		max-height: 440px;
		overflow: auto;
		scrollbar-color: rgba(160, 170, 188, 0.25) transparent;
	}

	.activity::-webkit-scrollbar { width: 6px; }
	.activity::-webkit-scrollbar-track { background: transparent; }
	.activity::-webkit-scrollbar-thumb {
		background: rgba(160, 170, 188, 0.2);
		border-radius: 999px;
	}

	.event-row {
		align-items: flex-start;
		justify-content: flex-start;
		gap: 0;
	}

	time {
		min-width: 82px;
		padding-top: 1px;
		font-size: 0.8rem;
		font-variant-numeric: tabular-nums;
		color: var(--muted-soft);
		flex-shrink: 0;
	}

	.event-body {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}

	.event-body strong {
		font-family: 'Avenir Next', 'Segoe UI', sans-serif;
		font-size: 0.88rem;
		font-weight: 500;
		text-transform: capitalize;
	}

	.ev-job { color: #60a5fa; }
	.ev-node { color: #a78bfa; }
	.ev-token { color: var(--accent); }
	.ev-default { color: #e8ecf4; }

	/* ── Leaderboard ──────────────────────────── */

	.leaderboard {
		margin-top: 12px;
	}

	.leader-name {
		display: flex;
		align-items: center;
		gap: 10px;
	}

	.rank {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 38px;
		height: 22px;
		padding: 0 7px;
		border-radius: 5px;
		font-size: 0.72rem;
		font-weight: 700;
		letter-spacing: 0.04em;
		background: rgba(255, 255, 255, 0.05);
		border: 1px solid rgba(255, 255, 255, 0.08);
		color: var(--muted);
	}

	.rank.gold {
		background: rgba(251, 191, 36, 0.14);
		border-color: rgba(251, 191, 36, 0.35);
		color: #fbbf24;
	}

	.rank.silver {
		background: rgba(148, 163, 184, 0.12);
		border-color: rgba(148, 163, 184, 0.3);
		color: #94a3b8;
	}

	.rank.bronze {
		background: rgba(180, 120, 60, 0.14);
		border-color: rgba(180, 120, 60, 0.35);
		color: #c97b3e;
	}

	/* ── Empty state ──────────────────────────── */

	.empty {
		margin: 0;
		padding: 14px 0;
		border-top: 1px solid var(--line);
		font-size: 0.88rem;
		color: var(--muted);
	}

	/* ── Responsive ───────────────────────────── */

	@media (max-width: 860px) {
		.shell {
			padding: 20px 12px 56px;
		}

		.hero {
			padding: 28px 22px 28px;
		}

		h1 {
			max-width: 20ch;
			margin-top: 2rem;
			font-size: clamp(2.6rem, 9vw, 3.8rem);
		}

		h2 {
			font-size: clamp(1.6rem, 6vw, 2.2rem);
		}

		.content-grid {
			grid-template-columns: 1fr;
		}

		.row {
			flex-direction: column;
			align-items: flex-start;
		}

		.row-meta {
			justify-content: flex-start;
		}

		time {
			min-width: 0;
		}
	}
</style>
