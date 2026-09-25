/*
 * Smoke checks for src/static/job_fields.js, run by tests/test_job_fields_js.py.
 *
 * Why this exists: the Python suite covers every route and every data-layer
 * helper, but nothing in it loads a line of the JavaScript those routes serve.
 * A refactor of job_fields.js once left `stop(e)` calling itself -- infinite
 * recursion on the first click in the table -- and the whole suite stayed
 * green. These checks close that gap: they load the real file, build every
 * field, and click everything that was built.
 *
 * Scope is deliberately smoke, not behaviour. Assertions about what a field
 * *renders* would encode the stub's limits as if they were the browser's. What
 * is asserted is that the module loads, the pure helpers compute, every builder
 * produces a subtree, and no handler blows the stack.
 *
 * Emits one JSON line per check on stdout so pytest can report each by name.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { document, dispatch } = require('./dom_stub.js');

const SOURCE = path.join(__dirname, '..', '..', 'src', 'static', 'job_fields.js');

const alerts = [];

const sandbox = {
  document,
  console,
  // Handlers that save are allowed to run; nothing here asserts on the write.
  fetch: async () => ({
    ok: true,
    status: 200,
    json: async () => ({ ok: true, rounds: [], recruiters: [] }),
  }),
  alert: (msg) => alerts.push(msg),
  // Decline every destructive prompt, so a click exercises the handler's
  // guard clauses without pretending the user said yes.
  confirm: () => false,
  prompt: () => null,
  setTimeout,
  URLSearchParams,
};
sandbox.window = sandbox;

const context = vm.createContext(sandbox);
// The file ends in `const JobFields = (...)()`; a trailing reference makes that
// binding the script's completion value, since a top-level const is lexical.
const JobFields = vm.runInContext(
  fs.readFileSync(SOURCE, 'utf8') + '\n;JobFields;',
  context,
  { filename: SOURCE },
);

// --- tiny check runner -----------------------------------------------------

const results = [];

function check(name, fn) {
  try {
    fn();
    results.push({ name, ok: true, error: null });
  } catch (err) {
    results.push({ name, ok: false, error: `${err && err.message}` });
  }
}

function assert(cond, msg) {
  if (!cond) throw new Error(msg || 'assertion failed');
}

function assertEqual(actual, expected, msg) {
  if (actual !== expected) {
    throw new Error(`${msg || 'not equal'}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
  }
}

// --- the module itself -----------------------------------------------------

const EXPORTS = [
  'rowKey', 'localISODate', 'startOfWeekISO', 'isValidISODate',
  'parseFollowupLog', 'serializeFollowupLog', 'jobKeyFields',
  'searchFromQuery', 'queryWithSearch', 'wantsArchived', 'searchBannerText',
  'renderMarkdownInto', 'appendInlineMarkdown', 'checkMarkdownOverflow',
  'refreshMarkdownFields', 'saveField', 'deleteJob', 'postJSON',
  'loadRecruiters', 'recruiterBadge', 'recruiterLabel', 'saveJobRecruiter',
  'createRecruiter', 'create',
];

check('module loads and exports its public surface', () => {
  assert(JobFields && typeof JobFields === 'object', 'JobFields is not an object');
  for (const name of EXPORTS) {
    assertEqual(typeof JobFields[name], 'function', `missing export ${name}`);
  }
});

// --- pure helpers ----------------------------------------------------------

check('rowKey joins the four-part composite key', () => {
  assertEqual(
    JobFields.rowKey({ company: 'Acme', date_added: '2026-01-02', position_title: 'Dev', link: 'https://x' }),
    'Acme::2026-01-02::Dev::https://x',
  );
});

check('rowKey leaves the optional halves blank rather than undefined', () => {
  assertEqual(JobFields.rowKey({ company: 'Acme', date_added: '2026-01-02' }), 'Acme::2026-01-02::::');
});

check('localISODate pads month and day', () => {
  assertEqual(JobFields.localISODate(new Date(2026, 0, 5)), '2026-01-05');
});

check('localISODate reads local time, not UTC', () => {
  // 23:30 local on the 5th is the 6th in UTC for a good part of the world;
  // the follow-up chips date against the user's day, so this must not shift.
  assertEqual(JobFields.localISODate(new Date(2026, 0, 5, 23, 30)), '2026-01-05');
});

check('startOfWeekISO winds back to Sunday', () => {
  // 2026-01-08 is a Thursday.
  assertEqual(JobFields.startOfWeekISO(new Date(2026, 0, 8)), '2026-01-04');
  // A Sunday is already the start of its week.
  assertEqual(JobFields.startOfWeekISO(new Date(2026, 0, 4)), '2026-01-04');
});

check('isValidISODate accepts a real date and rejects the rest', () => {
  assert(JobFields.isValidISODate('2026-01-05'), 'rejected a valid date');
  assert(!JobFields.isValidISODate(''), 'accepted empty');
  assert(!JobFields.isValidISODate(null), 'accepted null');
  assert(!JobFields.isValidISODate('05/01/2026'), 'accepted a non-ISO format');
  assert(!JobFields.isValidISODate('2026-1-5'), 'accepted an unpadded date');
  assert(!JobFields.isValidISODate('2026-13-01'), 'accepted month 13');
});

check('follow-up log round-trips through parse and serialize', () => {
  const raw = '2026-01-02, 2026-01-09';
  assertEqual(JobFields.serializeFollowupLog(JobFields.parseFollowupLog(raw)), raw);
});

check('parseFollowupLog drops blanks and surrounding space', () => {
  const tokens = JobFields.parseFollowupLog(' 2026-01-02 ,, 2026-01-09,');
  assertEqual(tokens.length, 2);
  assertEqual(tokens[0], '2026-01-02');
  assertEqual(tokens[1], '2026-01-09');
});

check('parseFollowupLog treats a missing log as empty', () => {
  assertEqual(JobFields.parseFollowupLog(null).length, 0);
  assertEqual(JobFields.parseFollowupLog(undefined).length, 0);
});

check('jobKeyFields blanks every missing half of the key', () => {
  const key = JobFields.jobKeyFields({ company: 'Acme' });
  assertEqual(JSON.stringify(key), JSON.stringify({
    company: 'Acme', date_added: '', position_title: '', link: '',
  }));
});

// --- deeplinked search -----------------------------------------------------
// The Insights page links to the table with ?q=<company>, and the table writes
// the box back into the URL as it is typed. Both directions are pure string
// work, which is why they live here and not in the template.

check('searchFromQuery reads q', () => {
  assertEqual(JobFields.searchFromQuery('?q=NACE%20Partners'), 'NACE Partners');
});

check('searchFromQuery is empty when there is no q', () => {
  assertEqual(JobFields.searchFromQuery(''), '');
  assertEqual(JobFields.searchFromQuery('?stage=rejected'), '');
});

check('searchFromQuery trims, so a stray space is not a filter', () => {
  assertEqual(JobFields.searchFromQuery('?q=%20%20Acme%20%20'), 'Acme');
});

check('queryWithSearch sets q', () => {
  assertEqual(JobFields.queryWithSearch('', 'Acme'), '?q=Acme');
});

check('queryWithSearch drops q when the box is cleared', () => {
  assertEqual(JobFields.queryWithSearch('?q=Acme', ''), '');
  assertEqual(JobFields.queryWithSearch('?q=Acme', '   '), '');
});

check('queryWithSearch leaves the funnel params alone', () => {
  // Arriving from the funnel and then typing must not drop the stage filter,
  // which is the only thing keeping archived rows in the list.
  const out = JobFields.queryWithSearch('?stage=rejected&source=hand', 'Acme');
  const p = new URLSearchParams(out);
  assertEqual(p.get('stage'), 'rejected');
  assertEqual(p.get('source'), 'hand');
  assertEqual(p.get('q'), 'Acme');
});

check('queryWithSearch returns empty rather than a bare ?', () => {
  // replaceState is called with pathname + this; a lone '?' would leave a
  // trailing character in the address bar for every cleared search.
  assertEqual(JobFields.queryWithSearch('', ''), '');
});

check('wantsArchived follows the funnel', () => {
  assertEqual(JobFields.wantsArchived('?stage=rejected'), true);
});

check('wantsArchived honours an explicit include_archived', () => {
  assertEqual(JobFields.wantsArchived('?q=Acme&include_archived=1'), true);
});

check('wantsArchived is false for a plain search', () => {
  // A typed search must not silently change the population being searched.
  assertEqual(JobFields.wantsArchived('?q=Acme'), false);
  assertEqual(JobFields.wantsArchived(''), false);
});

check('searchBannerText names the current query', () => {
  assertEqual(JobFields.searchBannerText('Sciforium'), 'Searching for “Sciforium”');
});

check('searchBannerText tracks whatever query it is given, not a stale one', () => {
  // The bug this guards: a banner computed once at load and never
  // recomputed would keep saying the arrival term after the box changed.
  assertEqual(JobFields.searchBannerText('Acme'), 'Searching for “Acme”');
});

check('searchBannerText is null once the box is cleared', () => {
  assertEqual(JobFields.searchBannerText(''), null);
  assertEqual(JobFields.searchBannerText('   '), null);
});

check('recruiterLabel pairs the name with the agency', () => {
  assertEqual(JobFields.recruiterLabel({ name: 'Dhruv', agency: 'AceStack' }), 'Dhruv — AceStack');
  assertEqual(JobFields.recruiterLabel({ recruiter_name: 'Dhruv', recruiter_agency: 'AceStack' }), 'Dhruv — AceStack');
});

check('recruiterLabel falls back when half the pair is missing', () => {
  assertEqual(JobFields.recruiterLabel({ name: 'Dhruv' }), 'Dhruv');
  assertEqual(JobFields.recruiterLabel({ agency: 'AceStack' }), '(unnamed) — AceStack');
  assertEqual(JobFields.recruiterLabel(null), '');
});

check('recruiterBadge shows nothing for a job with no recruiter', () => {
  assertEqual(JobFields.recruiterBadge({ company: 'Acme' }), null);
});

check('recruiterBadge marks a triage-linked recruiter apart from a typed one', () => {
  const typed = JobFields.recruiterBadge({ recruiter_id: 1, recruiter_agency: 'AceStack' });
  const triaged = JobFields.recruiterBadge({ recruiter_id: 1, recruiter_agency: 'AceStack', recruiter_from_triage: true });
  assert(!typed.className.includes('from-triage'), 'a typed link was marked from-triage');
  assert(triaged.className.includes('from-triage'), 'a triage link was not marked');
  assert(triaged.title.includes('inbox-triage'), 'the triage badge does not say where it came from');
});

// --- sorting ---------------------------------------------------------------

function jobs(...specs) {
  return specs.map(([company, date_added, status]) => ({
    company, date_added, status, position_title: '', location: '', link: '',
  }));
}

check('SORT_COLUMNS names a job field for every sortable column', () => {
  const sample = sampleJob();
  for (const [column, field] of Object.entries(JobFields.SORT_COLUMNS)) {
    assert(field in sample, `column ${column} reads a field no job has: ${field}`);
  }
});

check('compareJobs orders ascending and descending', () => {
  const rows = jobs(['Beta', '2026-01-02', 'Applied'], ['Alpha', '2026-01-03', 'Rejected']);
  const asc = rows.slice().sort(JobFields.compareJobs('company', 'asc')).map(j => j.company);
  const desc = rows.slice().sort(JobFields.compareJobs('company', 'desc')).map(j => j.company);
  assertEqual(asc.join(','), 'Alpha,Beta');
  assertEqual(desc.join(','), 'Beta,Alpha');
});

check('compareJobs sorts dates chronologically, not by digit', () => {
  const rows = jobs(['A', '2026-01-09', ''], ['B', '2026-01-10', ''], ['C', '2025-12-31', '']);
  const asc = rows.slice().sort(JobFields.compareJobs('date_added', 'asc')).map(j => j.company);
  assertEqual(asc.join(','), 'C,A,B');
});

check('a blank sorts last in both directions', () => {
  // A job with no date is not the oldest one; it is the one nobody recorded a
  // date for, and it belongs at the end either way.
  const rows = jobs(['A', '2026-01-02', ''], ['B', '', ''], ['C', '2026-01-01', '']);
  const asc = rows.slice().sort(JobFields.compareJobs('date_added', 'asc')).map(j => j.company);
  const desc = rows.slice().sort(JobFields.compareJobs('date_added', 'desc')).map(j => j.company);
  assertEqual(asc.join(','), 'C,A,B');
  assertEqual(desc.join(','), 'A,C,B');
});

check('whitespace counts as blank', () => {
  const rows = jobs(['A', '   ', ''], ['B', '2026-01-01', '']);
  const asc = rows.slice().sort(JobFields.compareJobs('date_added', 'asc')).map(j => j.company);
  assertEqual(asc.join(','), 'B,A');
});

check('compareJobs ignores case and reads embedded numbers as numbers', () => {
  const rows = jobs(['series 10', '', ''], ['Series 2', '', ''], ['SERIES 1', '', '']);
  const asc = rows.slice().sort(JobFields.compareJobs('company', 'asc')).map(j => j.company);
  assertEqual(asc.join(','), 'SERIES 1,Series 2,series 10');
});

check('an unknown column leaves the order untouched', () => {
  const rows = jobs(['B', '', ''], ['A', '', ''], ['C', '', '']);
  const same = rows.slice().sort(JobFields.compareJobs('nonsense', 'asc')).map(j => j.company);
  assertEqual(same.join(','), 'B,A,C');
});

check('sorting is stable, so a tie keeps the order the API sent', () => {
  const rows = jobs(['B', '2026-01-01', ''], ['A', '2026-01-01', ''], ['C', '2026-01-01', '']);
  const asc = rows.slice().sort(JobFields.compareJobs('date_added', 'asc')).map(j => j.company);
  assertEqual(asc.join(','), 'B,A,C');
});

check('nextSortDirection cycles asc, desc, then off', () => {
  assertEqual(JobFields.nextSortDirection(null), 'asc');
  assertEqual(JobFields.nextSortDirection('asc'), 'desc');
  assertEqual(JobFields.nextSortDirection('desc'), null);
});

// --- the builders ----------------------------------------------------------

function sampleJob() {
  return {
    company: 'Acme',
    date_added: '2026-01-02',
    position_title: 'Developer',
    location: 'Remote',
    link: 'https://example.invalid/jobs/1',
    status: 'Applied',
    notes: 'A note with **bold** in it.',
    summary: 'A summary.',
    contacts: '',
    followup_log: '2026-01-02',
    interview_date: '2026-01-20',
  };
}

const ROUNDS = [
  { id: 7, interview_type: 'Recruiter screen', scheduled_for: '2026-01-20', outcome: '' },
];

// Every builder, with the arguments its call sites pass.
function buildAll(fields) {
  const job = sampleJob();
  return [
    fields.makeDateField('Applied', job, 'date_added'),
    fields.renderDateInput(job, 'date_added'),
    fields.makeFollowupField('Follow-ups', job, 'followup_log'),
    fields.renderFollowupField(job, 'followup_log'),
    fields.makeDetailField('Status', job, 'status', false),
    fields.makeDetailField('Notes', job, 'notes', true),
    fields.makeMarkdownField('Summary', job, 'summary'),
    fields.makeRecruiterField(job, () => {}),
    fields.makeInterviewsField(job, ROUNDS),
    fields.makeDeleteField(job),
  ];
}

for (const stopClicks of [false, true]) {
  const label = stopClicks ? 'table' : 'modal';
  const fields = JobFields.create({
    fieldClass: stopClicks ? 'detail-field' : 'modal-field',
    notesClass: stopClicks ? ' notes-field' : '',
    stopClicks,
    tagFields: !stopClicks,
    interviewTypes: ['Recruiter screen', 'Technical'],
  });

  check(`${label}: create() returns every builder both views call`, () => {
    for (const name of [
      'makeDateField', 'renderDateInput', 'makeFollowupField', 'renderFollowupField',
      'makeDetailField', 'makeMarkdownField', 'makeRecruiterField',
      'makeInterviewsField', 'renderInterviews', 'reloadInterviews', 'makeDeleteField',
    ]) {
      assertEqual(typeof fields[name], 'function', `missing builder ${name}`);
    }
  });

  check(`${label}: every builder produces a subtree without throwing`, () => {
    for (const built of buildAll(fields)) {
      assert(built && typeof built.appendChild === 'function', 'a builder returned a non-element');
    }
  });

  check(`${label}: fields carry the wrapper class this view asked for`, () => {
    const wrapped = [
      fields.makeDateField('Applied', sampleJob(), 'date_added'),
      fields.makeDetailField('Status', sampleJob(), 'status', false),
      fields.makeMarkdownField('Summary', sampleJob(), 'summary'),
    ];
    const want = stopClicks ? 'detail-field' : 'modal-field';
    for (const el of wrapped) {
      assert(el.className.includes(want), `expected ${want}, got "${el.className}"`);
    }
  });

  check(`${label}: data-field tagging follows the tagFields flag`, () => {
    // The modal rebuilds in place and needs to find its fields again; the
    // table re-renders and does not.
    const el = fields.makeDetailField('Status', sampleJob(), 'status', false);
    const tagged = el.descendants().filter(n => n.dataset && n.dataset.field);
    if (stopClicks) assertEqual(tagged.length, 0, 'the table tagged fields it never looks up');
    else assert(tagged.length > 0, 'the modal built a field it cannot find again');
  });

  // The regression this whole file exists for: a handler that recurses, or
  // throws, on the first click. Clicking every node built is the cheapest
  // way to reach all of them.
  check(`${label}: clicking every built element runs its handlers to completion`, () => {
    for (const built of buildAll(fields)) {
      for (const node of built.descendants()) {
        try {
          dispatch(node, 'click');
        } catch (err) {
          if (err instanceof RangeError) {
            throw new Error(`click on <${node.tagName} class="${node.className}"> exhausted the stack: ${err.message}`);
          }
          throw new Error(`click on <${node.tagName} class="${node.className}"> threw: ${err.message}`);
        }
      }
    }
  });
}

// --- the one behavioural difference between the two views ------------------

check('stopClicks decides whether an edit click reaches the row behind it', () => {
  // The contract in the file header is about *interactive* elements: the
  // table's detail row collapses on any click that reaches it, so the field
  // the user types into swallows the click. Dead space -- the label, the
  // wrapper -- is not covered and still collapses the row, which is why this
  // aims at .editable rather than at every node.
  const row = document.createElement('div');
  let reachedRow = 0;
  row.addEventListener('click', () => { reachedRow += 1; });

  for (const stopClicks of [false, true]) {
    const fields = JobFields.create({ stopClicks });
    const field = fields.makeDetailField('Status', sampleJob(), 'status', false);
    row.appendChild(field);

    const editable = field.descendants().find(n => n.classList.contains('editable'));
    assert(editable, 'makeDetailField built no .editable to click');

    const before = reachedRow;
    dispatch(editable, 'click');
    const got = reachedRow - before;
    if (stopClicks) assertEqual(got, 0, 'the table let an edit click collapse its own detail row');
    else assertEqual(got, 1, 'the modal swallowed a click it has no ancestor handler for');
    field.remove();
  }
});

/*
 * Several handlers are async: they save, then touch the DOM again once the
 * write resolves. A throw in that tail arrives as an unhandled rejection long
 * after the click returned, so it is recorded as a failure rather than left to
 * kill the process with the results already printed.
 */
process.on('unhandledRejection', (err) => {
  results.push({
    name: 'no handler fails after its await',
    ok: false,
    error: `${err && err.message ? err.message : err}`,
  });
});

// Two turns of the loop: one to run the pending microtasks, one to see what
// they threw.
setImmediate(() => setImmediate(() => {
  for (const r of results) process.stdout.write(JSON.stringify(r) + '\n');
}));
