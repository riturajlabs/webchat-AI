import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

export function DocHeader({ title, lede }: { title: string; lede: string }) {
  return (
    <header className="flex flex-col gap-2">
      <h1 className="text-3xl font-bold tracking-tight">{title}</h1>
      <p className="max-w-2xl text-base text-muted-foreground">{lede}</p>
    </header>
  );
}

export function DocSection({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader className="p-4 pb-2">
        <CardTitle className="text-base">{title}</CardTitle>
        {description ? <CardDescription className="text-sm">{description}</CardDescription> : null}
      </CardHeader>
      <CardContent className="flex flex-col gap-4 p-4 pt-2">{children}</CardContent>
    </Card>
  );
}

export function SubHeading({ children }: { children: React.ReactNode }) {
  return <h2 className="text-sm font-medium text-muted-foreground">{children}</h2>;
}

export function Bullets({ items }: { items: React.ReactNode[] }) {
  return (
    <ul className="list-disc pl-5 text-sm text-muted-foreground">
      {items.map((item, index) => (
        <li key={index}>{item}</li>
      ))}
    </ul>
  );
}
