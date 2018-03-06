import json
import requests
from changebot.github.github_api import HOST
from changebot.github.github_auth import github_request_headers, get_json_web_token, get_installation_token


from flask import Blueprint, request, current_app

circleci = Blueprint('circleci', __name__)


def build_repo_to_install_mapping():
    url = 'https://api.github.com/app/installations'
    headers = {}
    headers['Authorization'] = 'Bearer {0}'.format(get_json_web_token())
    headers['Accept'] = 'application/vnd.github.machine-man-preview+json'
    resp = requests.get(url, headers=headers)
    payload = resp.json()

    ids = [p['id'] for p in payload]

    repos = {}
    for iid in ids:
        headers = github_request_headers(iid)
        resp = requests.get(f'{HOST}/installation/repositories', headers=headers)
        payload = resp.json()
        print(payload)
        for repo in payload['repositories']:
            repos[repo['full_name']] = iid

    return repos


@circleci.route('/circleci', methods=['POST'])
def circleci_handler():
    # Get installation id
    repos = build_repo_to_install_mapping()

    if not request.data:
        print("No payload received")

    payload = json.loads(request.data)['payload']

    # Validate we have the keys we need, otherwise ignore the push
    required_keys = {'vcs_revision',
                     'username',
                     'reponame',
                     'status',
                     'build_num'}

    if not required_keys.issubset(payload.keys()):
        return 'Payload missing {}'.format(' '.join(required_keys - payload.keys()))

    if payload['status'] == 'success':
        artifacts = get_artifacts_from_build(payload)
        url = get_documentation_url_from_artifacts(artifacts)

        if url:
            repo = f"{payload['username']}/{payload['reponame']}"
            set_commit_status(repo, repos[repo],
                              payload['vcs_revision'], "success",
                              "Click details to preview the documentation build", url)

    return "All good"


def get_artifacts_from_build(p):
    base_url = "https://circleci.com/api/v1.1"
    query_url = f"{base_url}/project/github/{p['username']}/{p['reponame']}/{p['build_num']}/artifacts"
    response = requests.get(query_url)
    assert response.ok, response.content
    return response.json()


def get_documentation_url_from_artifacts(artifacts):
    for artifact in artifacts:
        # Find the root sphinx index.html
        if "html/index.html" in artifact['path']:
            return artifact['url']


def set_commit_status(repository, installation, commit_hash, state, description, target_url):

    headers = github_request_headers(installation)

    set_status(repository, commit_hash, state, description, "Documentation",
               headers=headers, target_url=target_url)


def set_status(repository, commit_hash, state, description, context, *, headers, target_url=None):
    """
    Set status message in a pull request on GitHub.

    Parameters
    ----------
    state : { 'pending' | 'success' | 'error' | 'failure' }
        The state to set for the pull request.

    description : str
        The message that appears in the status line.

    context : str
        A string used to identify the status line.

    target_url : str or `None`
        Link to bot comment that is relevant to this status, if given.

    """

    data = {}
    data['state'] = state
    data['description'] = description
    data['context'] = context

    if target_url is not None:
        data['target_url'] = target_url

    url = f'{HOST}/repos/{repository}/statuses/{commit_hash}'
    response = requests.post(url, json=data, headers=headers)
    assert response.ok, response.content
