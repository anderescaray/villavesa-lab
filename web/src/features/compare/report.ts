/** Report actions: fetch the self-contained HTML from `/api/report` and open, save or print it. */
import { optimizerApi, type ReportRequest } from '@/api/optimizer';

export type ReportAction = 'open' | 'download' | 'print';

const fileName = (title: string) =>
  `${
    title
      .normalize('NFD')
      .replace(/[̀-ͯ]/g, '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 60) || 'villavesa-report'
  }.html`;

/**
 * Run a report action. The tab is opened synchronously (inside the click) so popup blockers
 * allow it, then filled once the report arrives. Returns false when the browser blocked the tab.
 */
export async function runReport(action: ReportAction, req: ReportRequest): Promise<boolean> {
  const tab = action === 'download' ? null : window.open('', '_blank');
  if (action !== 'download' && !tab) return false;
  try {
    const html = await optimizerApi.report(req);
    if (action === 'download') {
      const url = URL.createObjectURL(new Blob([html], { type: 'text/html;charset=utf-8' }));
      const a = document.createElement('a');
      a.href = url;
      a.download = fileName(req.title);
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } else if (action === 'open') {
      const url = URL.createObjectURL(new Blob([html], { type: 'text/html;charset=utf-8' }));
      tab!.location.replace(url);
    } else {
      tab!.document.open();
      tab!.document.write(html);
      tab!.document.close();
      window.setTimeout(() => tab!.print(), 400);
    }
    return true;
  } catch (e) {
    tab?.close();
    throw e;
  }
}
