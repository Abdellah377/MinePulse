import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import type { ProductionRecord } from "@/lib/mock/types"

export function ProductionTrendChart({ data }: { data: ProductionRecord[] }) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <AreaChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -16 }}>
        <defs>
          <linearGradient id="tonnageFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#1d8943" stopOpacity={0.28} />
            <stop offset="100%" stopColor="#1d8943" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="#d0d8d4" strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="label"
          tick={{ fill: "#5b6b64", fontSize: 10 }}
          axisLine={{ stroke: "#d0d8d4" }}
          tickLine={false}
        />
        <YAxis
          tick={{ fill: "#5b6b64", fontSize: 10 }}
          axisLine={false}
          tickLine={false}
          width={40}
        />
        <Tooltip
          contentStyle={{
            background: "#ffffff",
            border: "1px solid #d0d8d4",
            borderRadius: 4,
            fontSize: 11,
          }}
          labelStyle={{ color: "#5b6b64" }}
          itemStyle={{ color: "#1c2421" }}
        />
        <Area
          type="monotone"
          dataKey="tonnage"
          stroke="#1d8943"
          strokeWidth={2}
          fill="url(#tonnageFill)"
          name="Réel"
        />
        <Line
          type="monotone"
          dataKey="target"
          stroke="#8a9490"
          strokeWidth={1.5}
          strokeDasharray="4 4"
          dot={false}
          name="Objectif"
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}
