import type { ReactNode } from 'react';

import { SIZE } from '@/constants';
import { cn } from '@/lib/cn';

/**
 * Typed column definition. `render` receives the row, so cells stay type-safe
 * without the table needing to know anything about the row shape.
 */
export interface Column<TRow> {
  /** Stable key, also used for the React key. */
  readonly key: string;
  readonly header: string;
  readonly render: (row: TRow) => ReactNode;
  /** Numeric columns are right-aligned with tabular figures. */
  readonly numeric?: boolean;
  readonly width?: string;
  /** Hide below the tablet breakpoint to keep narrow layouts readable. */
  readonly hideOnNarrow?: boolean;
}

interface DataTableProps<TRow> {
  readonly columns: readonly Column<TRow>[];
  readonly rows: readonly TRow[];
  readonly rowKey: (row: TRow) => string;
  readonly onRowClick?: (row: TRow) => void;
  /** Rendered in place of the table body when there are no rows. */
  readonly emptyState?: ReactNode;
  readonly caption?: string;
  readonly footer?: ReactNode;
  readonly className?: string;
}

/**
 * Data table: 40px rows, hairline dividers, sticky header in the eyebrow type
 * style, right-aligned numerics with tabular figures, zebra striping OFF
 * (SRS §28.5).
 */
export function DataTable<TRow>({
  columns,
  rows,
  rowKey,
  onRowClick,
  emptyState,
  caption,
  footer,
  className,
}: DataTableProps<TRow>) {
  if (rows.length === 0 && emptyState !== undefined) {
    return <div className={className}>{emptyState}</div>;
  }

  const interactive = onRowClick !== undefined;

  return (
    <div
      className={cn(
        'overflow-x-auto rounded-sharp border border-line bg-card',
        className,
      )}
    >
      <table className="w-full border-collapse text-left">
        {caption !== undefined ? (
          <caption className="sr-only">{caption}</caption>
        ) : null}

        <thead>
          <tr className="border-b border-line">
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                style={column.width !== undefined ? { width: column.width } : undefined}
                className={cn(
                  'sticky top-0 z-10 bg-card px-4 py-2.5',
                  'text-eyebrow font-semibold uppercase tracking-[0.08em] text-ink-secondary',
                  column.numeric === true && 'text-right',
                  column.hideOnNarrow === true && 'hidden xl:table-cell',
                )}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>

        <tbody>
          {rows.map((row) => (
            <tr
              key={rowKey(row)}
              onClick={interactive ? () => onRowClick(row) : undefined}
              className={cn(
                'border-b border-line last:border-b-0',
                interactive && 'cursor-pointer transition-colors hover:bg-subtle',
              )}
              style={{ height: SIZE.tableRowHeight }}
            >
              {columns.map((column) => (
                <td
                  key={column.key}
                  className={cn(
                    'px-4 py-2 align-middle text-body text-ink',
                    column.numeric === true && 'text-right font-mono',
                    column.hideOnNarrow === true && 'hidden xl:table-cell',
                  )}
                  data-numeric={column.numeric === true ? '' : undefined}
                >
                  {column.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>

        {footer !== undefined ? (
          <tfoot className="border-t border-line bg-subtle">
            <tr>
              <td colSpan={columns.length} className="px-4 py-3">
                {footer}
              </td>
            </tr>
          </tfoot>
        ) : null}
      </table>
    </div>
  );
}
