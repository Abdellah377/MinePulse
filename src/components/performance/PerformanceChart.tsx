import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import type { PerfAnalysis } from "@/lib/performance/metrics"

const GRID = "#e0e5e2"
const TICK = { fill: "#5f6f68", fontSize: 10 }
const TIP = {
  contentStyle: {
    background: "#ffffff",
    border: "1px solid #e0e5e2",
    borderRadius: 8,
    fontSize: 11,
  },
}

const CHART_H = 280

export function PerformanceChart({ analysis }: { analysis: PerfAnalysis }) {
  const { chartKind, chartData, chartSeries } = analysis
  if (!chartData.some((row) => chartSeries.some((series) => typeof row[series.key] === "number"))) {
    return <p className="py-12 text-center text-xs text-muted">Mesures indisponibles pour ce graphique.</p>
  }

  return (
    <div
      className="relative w-full shrink-0 overflow-hidden"
      style={{ height: CHART_H, isolation: "isolate" }}
    >
      <ResponsiveContainer width="100%" height={CHART_H} debounce={50}>
        {chartKind === "line" ? (
          <LineChart data={chartData} margin={{ left: 4, right: 12, top: 8, bottom: 8 }}>
            <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="hour" tick={TICK} axisLine={false} tickLine={false} />
            <YAxis tick={TICK} axisLine={false} tickLine={false} width={40} />
            <Tooltip {...TIP} />
            {chartSeries.map((s) => (
              <Line
                key={s.key}
                type="monotone"
                dataKey={s.key}
                name={s.name}
                stroke={s.color}
                strokeWidth={s.key === "target" ? 1.5 : 2}
                strokeDasharray={s.key === "target" ? "4 4" : undefined}
                dot={false}
              />
            ))}
          </LineChart>
        ) : chartKind === "hbar" ? (
          <BarChart
            data={chartData}
            layout="vertical"
            margin={{ left: 4, right: 12, top: 8, bottom: 8 }}
          >
            <CartesianGrid stroke={GRID} strokeDasharray="3 3" horizontal={false} />
            <XAxis type="number" tick={TICK} axisLine={false} tickLine={false} />
            <YAxis
              type="category"
              dataKey="name"
              width={96}
              tick={TICK}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip {...TIP} />
            {chartSeries.map((s) => (
              <Bar key={s.key} dataKey={s.key} name={s.name} fill={s.color} radius={[0, 4, 4, 0]} />
            ))}
          </BarChart>
        ) : (
          <BarChart data={chartData} margin={{ left: 4, right: 12, top: 8, bottom: 48 }}>
            <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="name"
              tick={TICK}
              axisLine={false}
              tickLine={false}
              interval={0}
              angle={-28}
              textAnchor="end"
              height={48}
            />
            <YAxis tick={TICK} axisLine={false} tickLine={false} width={36} />
            <Tooltip {...TIP} />
            {chartSeries.map((s) => (
              <Bar
                key={s.key}
                dataKey={s.key}
                name={s.name}
                fill={s.color}
                stackId={chartKind === "stacked" ? "a" : undefined}
                radius={chartKind === "stacked" ? 0 : [4, 4, 0, 0]}
              >
                {chartKind === "histogram" &&
                  chartData.map((row, i) => (
                    <Cell
                      key={i}
                      fill={row.targetBand ? "#1d8943" : s.color ?? "#3a7bd5"}
                      fillOpacity={row.targetBand ? 1 : 0.75}
                    />
                  ))}
              </Bar>
            ))}
          </BarChart>
        )}
      </ResponsiveContainer>
    </div>
  )
}
