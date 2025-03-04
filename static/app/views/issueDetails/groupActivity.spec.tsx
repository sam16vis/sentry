import {Repository} from 'sentry-fixture/repository';

import {initializeOrg} from 'sentry-test/initializeOrg';
import {
  act,
  render,
  renderGlobalModal,
  screen,
  userEvent,
  waitFor,
} from 'sentry-test/reactTestingLibrary';

import ConfigStore from 'sentry/stores/configStore';
import GroupStore from 'sentry/stores/groupStore';
import OrganizationStore from 'sentry/stores/organizationStore';
import ProjectsStore from 'sentry/stores/projectsStore';
import TeamStore from 'sentry/stores/teamStore';
import {Group, GroupActivityType, Organization} from 'sentry/types';
import {GroupActivity} from 'sentry/views/issueDetails/groupActivity';

describe('GroupActivity', function () {
  let project;
  const dateCreated = '2021-10-01T15:31:38.950115Z';

  beforeEach(function () {
    project = TestStubs.Project();
    ProjectsStore.loadInitialData([project]);
    ConfigStore.init();
    ConfigStore.set('user', TestStubs.User({id: '123'}));
    GroupStore.init();
  });

  afterEach(() => {
    MockApiClient.clearMockResponses();
    jest.clearAllMocks();
  });

  function createWrapper({
    activity,
    organization: additionalOrg,
  }: {
    activity?: Group['activity'];
    organization?: Organization;
  } = {}) {
    const group = TestStubs.Group({
      id: '1337',
      activity: activity ?? [
        {type: 'note', id: 'note-1', data: {text: 'Test Note'}, user: TestStubs.User()},
      ],
      project,
    });
    const {organization, routerContext, routerProps} = initializeOrg({
      organization: additionalOrg,
    });
    GroupStore.add([group]);
    TeamStore.loadInitialData([TestStubs.Team({id: '999', slug: 'no-team'})]);
    OrganizationStore.onUpdate(organization, {replace: true});
    return render(
      <GroupActivity
        {...routerProps}
        api={new MockApiClient()}
        params={{orgId: 'org-slug'}}
        group={group}
        organization={organization}
      />,
      {context: routerContext}
    );
  }

  it('renders a NoteInput', function () {
    createWrapper();
    expect(screen.getByTestId('activity-note-body')).toBeInTheDocument();
  });

  it('renders a marked reviewed activity', function () {
    const user = TestStubs.User({name: 'Samwise'});
    createWrapper({
      activity: [
        {
          type: GroupActivityType.MARK_REVIEWED,
          id: 'reviewed-1',
          dateCreated: '',
          project: TestStubs.Project(),
          data: {},
          user,
        },
      ],
    });
    expect(screen.getByText('marked this issue as reviewed')).toBeInTheDocument();
    expect(screen.getByText(user.name)).toBeInTheDocument();
  });

  it('renders a pr activity', function () {
    const user = TestStubs.User({name: 'Test User'});
    const repository = Repository();
    createWrapper({
      activity: [
        {
          dateCreated: '',
          project: TestStubs.Project(),
          type: GroupActivityType.SET_RESOLVED_IN_PULL_REQUEST,
          id: 'pr-1',
          data: {
            pullRequest: {
              externalUrl: '',
              id: '',
              title: '',
              repository,
            },
          },
          user,
        },
      ],
    });
    expect(screen.getAllByTestId('activity-item').at(-1)).toHaveTextContent(
      'Test User has created a PR for this issue:'
    );
  });

  it('renders a assigned to self activity', function () {
    const user = TestStubs.User({id: '123', name: 'Mark'});
    createWrapper({
      activity: [
        {
          data: {
            assignee: user.id,
            assigneeEmail: user.email,
            assigneeType: 'user',
            user,
          },
          user,
          dateCreated: '2021-10-01T15:31:38.950115Z',
          id: '117',
          project: TestStubs.Project(),
          type: GroupActivityType.ASSIGNED,
        },
      ],
    });
    expect(screen.getAllByTestId('activity-item').at(-1)).toHaveTextContent(
      /Mark assigned this issue to themselves/
    );
  });

  it('renders an assigned via codeowners activity', function () {
    createWrapper({
      activity: [
        {
          data: {
            assignee: '123',
            assigneeEmail: 'anotheruser@sentry.io',
            assigneeType: 'user',
            integration: 'codeowners',
            rule: 'path:something/*.py #workflow',
            user: TestStubs.User(),
          },
          project: TestStubs.Project(),
          dateCreated: '2021-10-01T15:31:38.950115Z',
          id: '117',
          type: GroupActivityType.ASSIGNED,
          user: null,
        },
      ],
    });
    expect(screen.getAllByTestId('activity-item').at(-1)).toHaveTextContent(
      /Sentry auto-assigned this issue to anotheruser@sentry.io/
    );
  });

  it('renders an assigned via slack activity', function () {
    const user = TestStubs.User({id: '301', name: 'Mark'});
    createWrapper({
      activity: [
        {
          data: {
            assignee: '123',
            assigneeEmail: 'anotheruser@sentry.io',
            assigneeType: 'user',
            integration: 'slack',
            user: TestStubs.User(),
          },
          project: TestStubs.Project(),
          dateCreated: '2021-10-01T15:31:38.950115Z',
          id: '117',
          type: GroupActivityType.ASSIGNED,
          user,
        },
      ],
    });
    const item = screen.getAllByTestId('activity-item').at(-1);
    expect(item).toHaveTextContent(/Mark assigned this issue to anotheruser@sentry.io/);
    expect(item).toHaveTextContent(/Assigned via Slack/);
  });

  it('resolved in commit with no releases', function () {
    createWrapper({
      activity: [
        {
          type: GroupActivityType.SET_RESOLVED_IN_COMMIT,
          id: '123',
          project: TestStubs.Project(),
          dateCreated: '',
          data: {
            commit: {
              dateCreated: '',
              message: '',
              id: 'komal-commit',
              repository: Repository(),
              releases: [],
            },
          },
          user: TestStubs.User(),
        },
      ],
    });
    expect(screen.getAllByTestId('activity-item').at(-1)).toHaveTextContent(
      'Foo Bar marked this issue as resolved in komal-commit'
    );
  });

  it('resolved in commit with one release', function () {
    createWrapper({
      activity: [
        {
          type: GroupActivityType.SET_RESOLVED_IN_COMMIT,
          id: '123',
          project: TestStubs.Project(),
          dateCreated: '',
          data: {
            commit: {
              id: 'komal-commit',
              dateCreated: '',
              message: '',
              repository: Repository(),
              releases: [
                TestStubs.Release({
                  dateCreated: '2022-05-01',
                  dateReleased: '2022-05-02',
                  version: 'random',
                }),
              ],
            },
          },
          user: TestStubs.User(),
        },
      ],
    });
    expect(screen.getAllByTestId('activity-item').at(-1)).toHaveTextContent(
      'Foo Bar marked this issue as resolved in komal-commit This commit was released in random'
    );
  });

  it('resolved in commit with multiple releases', function () {
    createWrapper({
      activity: [
        {
          type: GroupActivityType.SET_RESOLVED_IN_COMMIT,
          id: '123',
          project: TestStubs.Project(),
          dateCreated: '',
          data: {
            commit: {
              id: 'komal-commit',
              dateCreated: '',
              message: '',
              repository: Repository(),
              releases: [
                TestStubs.Release({
                  dateCreated: '2022-05-01',
                  dateReleased: '2022-05-02',
                  version: 'random',
                }),
                TestStubs.Release({
                  dateCreated: '2022-06-01',
                  dateReleased: '2022-06-02',
                  version: 'newest',
                }),
                TestStubs.Release({
                  dateCreated: '2021-08-03',
                  dateReleased: '2021-08-03',
                  version: 'oldest-release',
                }),
                TestStubs.Release({
                  dateCreated: '2022-04-21',
                  dateReleased: '2022-04-21',
                  version: 'randomTwo',
                }),
              ],
            },
          },
          user: TestStubs.User(),
        },
      ],
    });
    expect(screen.getAllByTestId('activity-item').at(-1)).toHaveTextContent(
      'Foo Bar marked this issue as resolved in komal-commit This commit was released in oldest-release and 3 others'
    );
  });

  it('requests assignees that are not in the team store', async function () {
    const team = TestStubs.Team({id: '123', name: 'workflow'});
    const teamRequest = MockApiClient.addMockResponse({
      url: `/organizations/org-slug/teams/`,
      body: [team],
    });
    createWrapper({
      activity: [
        {
          id: '123',
          user: null,
          type: GroupActivityType.ASSIGNED,
          project: TestStubs.Project(),
          data: {
            assignee: team.id,
            assigneeType: 'team',
            user: TestStubs.User(),
          },
          dateCreated: '2021-10-28T13:40:10.634821Z',
        },
      ],
    });

    await waitFor(() => expect(teamRequest).toHaveBeenCalledTimes(1));
    expect(
      await screen.findByText(`assigned this issue to #${team.slug}`)
    ).toBeInTheDocument();
    expect(screen.getAllByTestId('activity-item').at(-1)).toHaveTextContent(
      /Sentry assigned this issue to #team-slug/
    );
  });

  describe('Delete', function () {
    let deleteMock;

    beforeEach(function () {
      deleteMock = MockApiClient.addMockResponse({
        url: '/organizations/org-slug/issues/1337/comments/note-1/',
        method: 'DELETE',
      });
      ConfigStore.set('user', TestStubs.User({id: '123', isSuperuser: true}));
    });

    it('should do nothing if not present in GroupStore', async function () {
      createWrapper();
      renderGlobalModal();
      act(() => {
        // Remove note from group activity
        GroupStore.removeActivity('1337', 'note-1');
      });

      await userEvent.click(screen.getByRole('button', {name: 'Comment Actions'}));
      await userEvent.click(screen.getByRole('menuitemradio', {name: 'Remove'}));
      expect(
        screen.getByText('Are you sure you wish to delete this comment?')
      ).toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', {name: 'Confirm'}));

      expect(deleteMock).not.toHaveBeenCalled();
    });

    it('should remove remove the item from the GroupStore make a DELETE API request', async function () {
      createWrapper();
      renderGlobalModal();

      await userEvent.click(screen.getByRole('button', {name: 'Comment Actions'}));
      await userEvent.click(screen.getByRole('menuitemradio', {name: 'Remove'}));
      expect(
        screen.getByText('Are you sure you wish to delete this comment?')
      ).toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', {name: 'Confirm'}));

      expect(deleteMock).toHaveBeenCalledTimes(1);
    });
  });

  it('renders ignored', function () {
    createWrapper({
      activity: [
        {
          id: '123',
          type: GroupActivityType.SET_IGNORED,
          project: TestStubs.Project(),
          data: {
            ignoreUntilEscalating: true,
          },
          user: TestStubs.User(),
          dateCreated,
        },
      ],
    });
    expect(screen.getAllByTestId('activity-item').at(-1)).toHaveTextContent(
      'Foo Bar ignored this issue'
    );
  });

  it('renders archived until escalating if org has `escalating-issues` feature', function () {
    createWrapper({
      activity: [
        {
          id: '123',
          type: GroupActivityType.SET_IGNORED,
          project: TestStubs.Project(),
          data: {
            ignoreUntilEscalating: true,
          },
          user: TestStubs.User(),
          dateCreated,
        },
      ],
      organization: TestStubs.Organization({features: ['escalating-issues']}),
    });
    expect(screen.getAllByTestId('activity-item').at(-1)).toHaveTextContent(
      'Foo Bar archived this issue until it escalates'
    );
  });

  it('renders escalating with forecast and plural events if org has `escalating-issues` feature', function () {
    createWrapper({
      activity: [
        {
          id: '123',
          type: GroupActivityType.SET_UNRESOLVED,
          project: TestStubs.Project(),
          data: {
            forecast: 200,
          },
          user: null,
          dateCreated,
        },
        {
          id: '124',
          type: GroupActivityType.SET_ESCALATING,
          project: TestStubs.Project(),
          data: {
            forecast: 400,
          },
          user: null,
          dateCreated: '2021-10-05T15:31:38.950115Z',
        },
      ],
      organization: TestStubs.Organization({features: ['escalating-issues']}),
    });
    expect(screen.getAllByTestId('activity-item').at(-1)).toHaveTextContent(
      'Sentry flagged this issue as escalating because over 400 events happened in an hour'
    );
    expect(screen.getAllByTestId('activity-item').at(-2)).toHaveTextContent(
      'Sentry flagged this issue as escalating because over 200 events happened in an hour'
    );
  });

  it('renders escalating with forecast and singular event if org has `escalating-issues` feature', function () {
    createWrapper({
      activity: [
        {
          id: '123',
          type: GroupActivityType.SET_UNRESOLVED,
          project: TestStubs.Project(),
          data: {
            forecast: 1,
          },
          user: null,
          dateCreated,
        },
      ],
      organization: TestStubs.Organization({features: ['escalating-issues']}),
    });
    expect(screen.getAllByTestId('activity-item').at(-1)).toHaveTextContent(
      'Sentry flagged this issue as escalating because over 1 event happened in an hour'
    );
  });

  it('renders ignored until it happens x times in time window', function () {
    createWrapper({
      activity: [
        {
          id: '123',
          type: GroupActivityType.SET_IGNORED,
          project: TestStubs.Project(),
          data: {
            ignoreCount: 400,
            ignoreWindow: 1,
          },
          user: TestStubs.User(),
          dateCreated,
        },
      ],
    });
    expect(screen.getAllByTestId('activity-item').at(-1)).toHaveTextContent(
      'Foo Bar ignored this issue until it happens 400 time(s) in 1 minute'
    );
  });

  it('renders escalating since it happened x times in time window', function () {
    createWrapper({
      activity: [
        {
          id: '123',
          type: GroupActivityType.SET_ESCALATING,
          project: TestStubs.Project(),
          data: {
            expired_snooze: {
              count: 400,
              window: 1,
              until: null,
              user_count: null,
              user_window: null,
            },
          },
          dateCreated,
        },
      ],
    });
    expect(screen.getAllByTestId('activity-item').at(-1)).toHaveTextContent(
      'Sentry flagged this issue as escalating because 400 events happened in 1 minute'
    );
  });

  it('renders escalating since x users were affected in time window', function () {
    createWrapper({
      activity: [
        {
          id: '123',
          type: GroupActivityType.SET_ESCALATING,
          project: TestStubs.Project(),
          data: {
            expired_snooze: {
              user_count: 1,
              user_window: 1,
              until: null,
              count: null,
              window: null,
            },
          },
          dateCreated,
        },
      ],
    });
    expect(screen.getAllByTestId('activity-item').at(-1)).toHaveTextContent(
      'Sentry flagged this issue as escalating because 1 user was affected in 1 minute'
    );
  });

  it('renders escalating since until date passed', function () {
    const date = new Date('2018-10-30');
    createWrapper({
      activity: [
        {
          id: '123',
          type: GroupActivityType.SET_ESCALATING,
          project: TestStubs.Project(),
          data: {
            expired_snooze: {
              until: date,
              user_count: null,
              user_window: null,
              count: null,
              window: null,
            },
          },
          dateCreated,
        },
      ],
    });
    expect(screen.getAllByTestId('activity-item').at(-1)).toHaveTextContent(
      'Sentry flagged this issue as escalating because Oct 30, 2018 12:00 AM passed'
    );
  });

  it('renders archived forever', function () {
    createWrapper({
      activity: [
        {
          id: '123',
          type: GroupActivityType.SET_IGNORED,
          project: TestStubs.Project(),
          data: {},
          user: TestStubs.User(),
          dateCreated,
        },
      ],
      organization: TestStubs.Organization({features: ['escalating-issues']}),
    });
    expect(screen.getAllByTestId('activity-item').at(-1)).toHaveTextContent(
      'Foo Bar archived this issue forever'
    );
  });

  it('renders resolved in release with semver information', function () {
    createWrapper({
      activity: [
        {
          id: '123',
          type: GroupActivityType.SET_RESOLVED_IN_RELEASE,
          project: TestStubs.Project(),
          data: {
            version: 'frontend@1.0.0',
          },
          user: TestStubs.User(),
          dateCreated,
        },
      ],
    });
    expect(screen.getAllByTestId('activity-item').at(-1)).toHaveTextContent(
      'Foo Bar marked this issue as resolved in 1.0.0 (semver)'
    );
  });

  it('renders resolved in next release with semver information', function () {
    createWrapper({
      activity: [
        {
          id: '123',
          type: GroupActivityType.SET_RESOLVED_IN_RELEASE,
          project: TestStubs.Project(),
          data: {
            current_release_version: 'frontend@1.0.0',
          },
          user: TestStubs.User(),
          dateCreated,
        },
      ],
    });
    expect(screen.getAllByTestId('activity-item').at(-1)).toHaveTextContent(
      'Foo Bar marked this issue as resolved in releases greater than 1.0.0 (semver)'
    );
  });

  describe('regression', function () {
    it('renders basic regression', function () {
      createWrapper({
        activity: [
          {
            id: '123',
            type: GroupActivityType.SET_REGRESSION,
            project: TestStubs.Project(),
            data: {},
            dateCreated,
          },
        ],
      });
      expect(screen.getAllByTestId('activity-item').at(-1)).toHaveTextContent(
        'Sentry marked this issue as a regression'
      );
    });
    it('renders regression with version', function () {
      createWrapper({
        activity: [
          {
            id: '123',
            type: GroupActivityType.SET_REGRESSION,
            project: TestStubs.Project(),
            data: {
              version: 'frontend@1.0.0',
            },
            dateCreated,
          },
        ],
      });
      expect(screen.getAllByTestId('activity-item').at(-1)).toHaveTextContent(
        'Sentry marked this issue as a regression in 1.0.0'
      );
    });
    it('renders regression with semver description', function () {
      createWrapper({
        activity: [
          {
            id: '123',
            type: GroupActivityType.SET_REGRESSION,
            project: TestStubs.Project(),
            data: {
              version: 'frontend@2.0.0',
              resolved_in_version: 'frontend@1.0.0',
              follows_semver: true,
            },
            dateCreated,
          },
        ],
      });
      const activity = screen.getAllByTestId('activity-item').at(-1);
      expect(activity).toHaveTextContent(
        'Sentry marked this issue as a regression in 2.0.0'
      );
      expect(activity).toHaveTextContent(
        '2.0.0 is greater than or equal to 1.0.0 compared via semver'
      );
    });
    it('renders regression with non-semver description', function () {
      createWrapper({
        activity: [
          {
            id: '123',
            type: GroupActivityType.SET_REGRESSION,
            project: TestStubs.Project(),
            data: {
              version: 'frontend@abc1',
              resolved_in_version: 'frontend@abc2',
              follows_semver: false,
            },
            dateCreated,
          },
        ],
      });
      const activity = screen.getAllByTestId('activity-item').at(-1);
      expect(activity).toHaveTextContent(
        'Sentry marked this issue as a regression in abc1'
      );
      expect(activity).toHaveTextContent(
        'abc1 is greater than or equal to abc2 compared via release date'
      );
    });
  });
});
