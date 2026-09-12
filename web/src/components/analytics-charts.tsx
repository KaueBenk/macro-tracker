"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Legend,
  Pie,
  PieChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  ChartContainer,
  ChartLegendContent,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import { formatNumber } from "@/components/progress-card";

const chartColors = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
];

const macroConfig: ChartConfig = {
  protein: {
    label: "Proteína",
    color: "var(--chart-1)",
  },
  carbs: {
    label: "Carboidrato",
    color: "var(--chart-2)",
  },
  fat: {
    label: "Gordura",
    color: "var(--chart-3)",
  },
};

export function CalorieDistributionChart({
  protein,
  carbs,
  fat,
}: {
  protein: number;
  carbs: number;
  fat: number;
}) {
  const data = [
    { name: "Proteína", value: protein, color: chartColors[0] },
    { name: "Carboidrato", value: carbs, color: chartColors[1] },
    { name: "Gordura", value: fat, color: chartColors[2] },
  ].filter((item) => item.value > 0);
  const total = data.reduce((sum, item) => sum + item.value, 0);
  if (!total) {
    return (
      <p className="py-12 text-center text-sm text-muted-foreground">
        Nenhuma entrada registrada para distribuir.
      </p>
    );
  }
  return (
    <div className="grid min-w-0 items-center gap-4 sm:grid-cols-[minmax(0,1fr)_auto]">
      <ChartContainer
        config={{}}
        className="mx-auto h-56 min-w-0 w-full max-w-[280px]"
      >
        <PieChart>
          <Tooltip
            content={<ChartTooltipContent />}
            formatter={(value: number) => `${formatNumber(value)} kcal`}
          />
          <Pie
            data={data}
            dataKey="value"
            nameKey="name"
            innerRadius={58}
            outerRadius={86}
            paddingAngle={3}
          >
            {data.map((item) => (
              <Cell key={item.name} fill={item.color} />
            ))}
          </Pie>
        </PieChart>
      </ChartContainer>
      <div className="min-w-0 space-y-3 text-sm">
        {data.map((item) => (
          <div key={item.name} className="flex items-center gap-2">
            <span className="size-2.5 rounded-sm" style={{ backgroundColor: item.color }} />
            <span>{item.name}</span>
            <span className="ml-auto pl-4 font-medium tabular-nums">
              {Math.round((item.value / total) * 100)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function MealCaloriesChart({ data }: { data: { meal: string; kcal: number }[] }) {
  if (!data.some((item) => item.kcal > 0)) {
    return (
      <p className="py-12 text-center text-sm text-muted-foreground">
        Nenhuma caloria registrada por refeição.
      </p>
    );
  }
  return (
    <ChartContainer
      config={{
        kcal: {
          label: "Calorias",
          color: "var(--chart-1)",
        },
      }}
      className="h-64 w-full"
    >
      <BarChart data={data} margin={{ left: 0, right: 8, top: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis
          dataKey="meal"
          tickLine={false}
          axisLine={false}
          tickMargin={8}
        />
        <YAxis
          tickLine={false}
          axisLine={false}
          tickFormatter={(value: number) => formatNumber(value)}
          width={56}
        />
        <Tooltip
          content={<ChartTooltipContent />}
          formatter={(value: number) => `${formatNumber(value)} kcal`}
        />
        <Bar
          dataKey="kcal"
          fill="var(--chart-1)"
          radius={[4, 4, 0, 0]}
        />
      </BarChart>
    </ChartContainer>
  );
}

export function CaloriesLineChart({
  data,
}: {
  data: { date: string; label: string; kcal: number; goal: number | null }[];
}) {
  if (
    !data.length ||
    !data.some((item) => item.kcal > 0 || item.goal !== null)
  ) {
    return (
      <p className="py-12 text-center text-sm text-muted-foreground">
        Nenhum registro ou meta disponível no período.
      </p>
    );
  }
  return (
    <ChartContainer
      config={{
        kcal: {
          label: "Calorias",
          color: "var(--chart-1)",
        },
        goal: {
          label: "Meta",
          color: "var(--chart-3)",
        },
      }}
      className="h-72 w-full"
    >
      <LineChart data={data} margin={{ left: 0, right: 8, top: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis
          dataKey="label"
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          minTickGap={24}
        />
        <YAxis
          tickLine={false}
          axisLine={false}
          tickFormatter={(value: number) => formatNumber(value)}
          width={56}
        />
        <Legend content={<ChartLegendContent />} />
        <Tooltip
          content={<ChartTooltipContent />}
          formatter={(value: number) => `${formatNumber(value)} kcal`}
        />
        <Line
          dataKey="kcal"
          type="linear"
          stroke="var(--chart-1)"
          strokeWidth={2}
          dot={false}
        />
        <Line
          dataKey="goal"
          type="linear"
          stroke="var(--chart-3)"
          strokeDasharray="5 5"
          strokeWidth={2}
          dot={false}
          connectNulls
        />
      </LineChart>
    </ChartContainer>
  );
}

export function MacroStackedChart({
  data,
}: {
  data: { label: string; protein: number; carbs: number; fat: number }[];
}) {
  if (!data.some((item) => item.protein + item.carbs + item.fat > 0)) {
    return (
      <p className="py-12 text-center text-sm text-muted-foreground">
        Nenhum macro registrado no período.
      </p>
    );
  }
  return (
    <ChartContainer config={macroConfig} className="h-72 w-full">
      <BarChart data={data} margin={{ left: 0, right: 8, top: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis
          dataKey="label"
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          minTickGap={24}
        />
        <YAxis
          tickLine={false}
          axisLine={false}
          tickFormatter={(value: number) => formatNumber(value)}
          width={56}
        />
        <Legend content={<ChartLegendContent />} />
        <Tooltip
          content={<ChartTooltipContent />}
          formatter={(value: number) => `${formatNumber(value)} g`}
        />
        <Bar
          dataKey="protein"
          stackId="macros"
          fill="var(--chart-1)"
          radius={[0, 0, 0, 0]}
        />
        <Bar dataKey="carbs" stackId="macros" fill="var(--chart-2)" />
        <Bar
          dataKey="fat"
          stackId="macros"
          fill="var(--chart-3)"
          radius={[4, 4, 0, 0]}
        />
      </BarChart>
    </ChartContainer>
  );
}
