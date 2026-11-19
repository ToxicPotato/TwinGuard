import type { LiveFrame } from '../../types';
import { chainComponents, robotLabel, STATE_COLORS } from '../../utils/label';
import { spoofKindLabel } from '../../utils/scenario';
import styles from './PlatoonDiagram.module.css';

interface AttackLink {
  targetRobot: string;  // leader — signal source being spoofed (NOT under attack)
  follower: string;     // robot receiving false data — the actual victim
  state: 'active' | 'pending';
}

interface Props {
  frame: LiveFrame | null;
  robotIds: string[];
  attacks: AttackLink[];
}

const ROBOT_W = 56;
const ROBOT_H = 38;
const STEP    = 92;
const COMP_GAP = 52;

// Vertical layout (SVG_H = 78):
//   ATTACK/ARMED badge  → ATTACK_Y = 12   (above follower robot box)
//   robot box           → y = 20 … 58
//   state dot           → LINE_Y = 39
//   VEL SPOOF text      → BRAKE_Y = 51    (inside box near bottom)
//   robot ID            → ID_Y = 69
const SVG_H    = 78;
const ROBOT_Y  = 20;
const ATTACK_Y = 12;
const LINE_Y   = ROBOT_Y + ROBOT_H / 2;   // 39
const BRAKE_Y  = ROBOT_Y + ROBOT_H - 7;   // 51
const ID_Y     = ROBOT_Y + ROBOT_H + 11;  // 69

function gapForFollower(id: string, frame: LiveFrame | null): number | null {
  const robot = frame?.robots?.[id];
  if (robot?.dv === true && robot.d != null) return robot.d;
  return frame?.low_res?.per_robot?.[id]?.assessment?.gap?.bumper_gap_meters ?? null;
}

export function PlatoonDiagram({ frame, robotIds, attacks }: Props) {
  const components = chainComponents(frame, robotIds);

  if (components.length === 0 || robotIds.length === 0) {
    return (
      <div className={styles.wrap}>
        <div className={styles.label}>PLATOON DIAGRAM</div>
        <div className={styles.empty}>NO LIVE ROBOTS</div>
      </div>
    );
  }

  const positions: Array<{ id: string; cx: number; compIdx: number }> = [];
  let cursor = STEP / 2 + 10;

  components.forEach((comp, compIdx) => {
    if (compIdx > 0) cursor += COMP_GAP;
    comp.forEach((id) => {
      positions.push({ id, cx: cursor, compIdx });
      cursor += STEP;
    });
  });

  const totalWidth = cursor + 10;

  // Lookup sets for O(1) membership checks
  const activeFollowers  = new Set(attacks.filter(a => a.state === 'active').map(a => a.follower));
  const pendingFollowers = new Set(attacks.filter(a => a.state === 'pending').map(a => a.follower));

  return (
    <div className={styles.wrap}>
      <div className={styles.label}>PLATOON DIAGRAM — FRONT LEFT</div>
      <svg
        className={styles.svg}
        viewBox={`0 0 ${totalWidth} ${SVG_H}`}
        preserveAspectRatio="xMidYMid meet"
      >
        <defs>
          <filter id="glow-red" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="2.5" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>

        {/* ── Component separators ──────────────────────────────────────── */}
        {components.slice(1).map((_, i) => {
          const lastOfPrev = positions.filter((p) => p.compIdx === i).at(-1);
          const firstOfNext = positions.find((p) => p.compIdx === i + 1);
          if (!lastOfPrev || !firstOfNext) return null;
          const sepX = (lastOfPrev.cx + firstOfNext.cx) / 2;
          return (
            <line
              key={`sep-${i}`}
              x1={sepX} y1={2} x2={sepX} y2={SVG_H - 2}
              stroke="rgba(255,224,64,0.55)"
              strokeWidth="1.5"
              strokeDasharray="4 3"
            />
          );
        })}

        {/* ── Connecting lines ─────────────────────────────────────────── */}
        {positions.map((pos, idx) => {
          if (idx === 0) return null;
          const prev = positions[idx - 1];
          if (prev.compIdx !== pos.compIdx) return null;

          const x1 = prev.cx + ROBOT_W / 2;
          const x2 = pos.cx  - ROBOT_W / 2;
          const midX = (x1 + x2) / 2;

          // Check if this specific communication link is under attack
          const attackOnLink = attacks.find(
            a => a.targetRobot === prev.id && a.follower === pos.id,
          );
          const isActiveLink  = attackOnLink?.state === 'active';
          const isPendingLink = attackOnLink?.state === 'pending';

          const gap = gapForFollower(pos.id, frame);
          const gapLabel = gap != null ? `${Math.abs(gap).toFixed(1)}m` : null;

          const lineStroke = isActiveLink
            ? 'rgba(255,48,96,0.7)'
            : isPendingLink
              ? 'rgba(255,160,0,0.6)'
              : 'var(--bdr2)';

          return (
            <g key={`link-${idx}`}>
              <line
                x1={x1} y1={LINE_Y} x2={x2} y2={LINE_Y}
                stroke={lineStroke}
                strokeWidth={attackOnLink ? 1.5 : 1}
                strokeDasharray={attackOnLink ? '5 2' : '4 3'}
              />

              {/* Attack badge on the link — shown instead of gap during attack */}
              {isActiveLink && (
                <g style={{ animation: 'pulse-red 0.8s infinite' }}>
                  <rect
                    x={midX - 26} y={LINE_Y - 13}
                    width={52} height={12}
                    rx={2}
                    fill="rgba(255,48,96,0.15)"
                    stroke="rgba(255,48,96,0.5)"
                    strokeWidth="0.5"
                  />
                  <text
                    x={midX} y={LINE_Y - 4}
                    textAnchor="middle"
                    fill="var(--red)"
                    fontFamily="var(--fmono)"
                    fontSize="8.5"
                    letterSpacing="1.5"
                    fontWeight="bold"
                  >
                    INTERCEPT
                  </text>
                </g>
              )}

              {isPendingLink && (
                <g style={{ animation: 'pulse-orange 1s infinite' }}>
                  <rect
                    x={midX - 22} y={LINE_Y - 13}
                    width={44} height={12}
                    rx={2}
                    fill="rgba(255,160,0,0.12)"
                    stroke="rgba(255,160,0,0.4)"
                    strokeWidth="0.5"
                  />
                  <text
                    x={midX} y={LINE_Y - 4}
                    textAnchor="middle"
                    fill="#ffa000"
                    fontFamily="var(--fmono)"
                    fontSize="8.5"
                    letterSpacing="1.5"
                    fontWeight="bold"
                  >
                    ARMED
                  </text>
                </g>
              )}

              {/* Gap label — shown only when link is not under attack */}
              {!attackOnLink && gapLabel != null && (
                <>
                  <rect
                    x={midX - 15} y={LINE_Y - 13}
                    width={30} height={11}
                    rx={2}
                    fill="rgba(0,229,255,0.08)"
                    stroke="rgba(0,229,255,0.25)"
                    strokeWidth="0.5"
                  />
                  <text
                    x={midX} y={LINE_Y - 5}
                    textAnchor="middle"
                    fill="var(--s0)"
                    fontFamily="var(--fmono)"
                    fontSize="8.5"
                    letterSpacing="0.4"
                  >
                    {gapLabel}
                  </text>
                </>
              )}
            </g>
          );
        })}

        {/* ── Robots ────────────────────────────────────────────────────── */}
        {positions.map(({ id, cx }) => {
          const robotData = frame?.robots?.[id];
          const st = robotData?.st ?? 0;
          const stColor = STATE_COLORS[Math.min(st, STATE_COLORS.length - 1)];

          const isActiveFollower  = activeFollowers.has(id);
          const isPendingFollower = !isActiveFollower && pendingFollowers.has(id);
          const isAffected = isActiveFollower || isPendingFollower;

          const velocitySpoof = frame?.scenario?.per_robot?.[id]?.velocity_spoof ?? false;
          const velocitySpoofKind = frame?.scenario?.per_robot?.[id]?.velocity_spoof_kind ?? null;
          const rx = cx - ROBOT_W / 2;

          const boxFill   = velocitySpoof ? 'rgba(255,48,96,0.20)' : `${stColor}18`;
          const boxStroke = isActiveFollower
            ? 'var(--red)'
            : isPendingFollower
              ? '#ffa000'
              : stColor;
          const boxWidth  = isAffected ? 2 : 1.5;

          return (
            <g key={id}>
              {/* Robot body */}
              <rect
                x={rx} y={ROBOT_Y}
                width={ROBOT_W} height={ROBOT_H}
                rx={5}
                fill={boxFill}
                stroke={boxStroke}
                strokeWidth={boxWidth}
                filter={velocitySpoof ? 'url(#glow-red)' : undefined}
                style={isActiveFollower ? { animation: 'blink-border 0.6s step-end infinite' } : undefined}
              />

              {/* State dot */}
              <circle cx={cx} cy={LINE_Y} r={4} fill={stColor} opacity={0.8} />

              {/* VEL SPOOF — twin confirmation, inside box near bottom */}
              {velocitySpoof && (
                <text
                  x={cx} y={BRAKE_Y}
                  textAnchor="middle"
                  fill="var(--red)"
                  fontFamily="var(--fmono)"
                  fontSize="7"
                  letterSpacing="1"
                  opacity={0.9}
                >
                  {velocitySpoofKind ? `VEL ${spoofKindLabel(velocitySpoofKind)}` : 'VEL SPOOF'}
                </text>
              )}

              {/* Robot ID */}
              <text
                x={cx} y={ID_Y}
                textAnchor="middle"
                fill={isAffected ? (isActiveFollower ? 'var(--red)' : '#ffa000') : 'var(--tx)'}
                fontFamily="var(--fmono)"
                fontSize="10"
                letterSpacing="1"
                fontWeight={isAffected ? 'bold' : 'normal'}
              >
                {robotLabel(id, true)}
              </text>

              {/* ATTACK — above follower box (the robot receiving false data) */}
              {isActiveFollower && (
                <g style={{ animation: 'pulse-red 0.8s infinite' }}>
                  <rect
                    x={cx - 24} y={ATTACK_Y - 10}
                    width={48} height={13}
                    rx={3}
                    fill="rgba(255,48,96,0.15)"
                    stroke="rgba(255,48,96,0.5)"
                    strokeWidth="0.5"
                  />
                  <text
                    x={cx} y={ATTACK_Y}
                    textAnchor="middle"
                    fill="var(--red)"
                    fontFamily="var(--fmono)"
                    fontSize="10"
                    letterSpacing="2"
                    fontWeight="bold"
                  >
                    ATTACK
                  </text>
                </g>
              )}

              {/* ARMED — above follower box when pending */}
              {isPendingFollower && (
                <g style={{ animation: 'pulse-orange 1s infinite' }}>
                  <rect
                    x={cx - 22} y={ATTACK_Y - 10}
                    width={44} height={13}
                    rx={3}
                    fill="rgba(255,160,0,0.12)"
                    stroke="rgba(255,160,0,0.4)"
                    strokeWidth="0.5"
                  />
                  <text
                    x={cx} y={ATTACK_Y}
                    textAnchor="middle"
                    fill="#ffa000"
                    fontFamily="var(--fmono)"
                    fontSize="10"
                    letterSpacing="2"
                    fontWeight="bold"
                  >
                    ARMED
                  </text>
                </g>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

