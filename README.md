# NEMO-online-training

[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/NEMO-online-training?label=python)](https://www.python.org/downloads/release/python-3110/)
[![PyPI](https://img.shields.io/pypi/v/nemo-online-training?label=pypi%20version)](https://pypi.org/project/NEMO-online-training/)
[![Changelog](https://img.shields.io/github/v/releaseusnistgov/NEMO-online-training?include_prereleases&label=changelog)](https://github.com/usnistgov/NEMO-online-training/releases)

Plugin for NEMO to allow users to complete online training even before they have a NEMO account

## Installation

```bash
python -m install nemo-online-training
```

in `settings.py` add to `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    '...',
    'NEMO_online_training',
    '...'
]
```

## Usage

Add online training in Administration -> Detailed administration -> Online trainings

For each training, you can optionally add an action to be performed when the user completes the training.

The following actions are available:
- extend the user's access expiration date (if the user is already a NEMO user):
  - in the configuration, you can specify the number of days to extend the access expiration date by using `extend_by_days`
- remove the training_required flag from the user
- send an email 
  - in the configuration, you can specify the email subject, message and recipients by using `subject` (django template syntax allowed), `message` (django template syntax allowed) and `recipients` (list of email addresses or `user` to send to the user)
  - in the subject and message, the following variables are available:
    - `training_user`: the user who is completing the training
    - `training`: the training being completed
    - `record`: the record of the training being completed
    - `action`: the action being performed (send email action)
- qualify the user on a tool
    - in the configuration, you can specify the tool ids to qualify the user on by using `tool_ids` (list of tool ids)
- grant physical access level to the user
    - in the configuration, you can specify the access level to grant by using `physical_access_level_ids` (list of physical access level ids)

Display options:
  - set `NEMO_ONLINE_TRAINING_ADMIN_NAME` in settings.py to customize the admin section name. Default is "Online training"
  - set `NEMO_ONLINE_TRAINING_ADMIN_TRAINING_NAME` in settings.py to customize the training model admin name. Default is "Training"
  - set `NEMO_ONLINE_TRAINING_ADMIN_TRAINING_USER_NAME` in settings.py to customize the training user model admin name. Default is "Training User"
  - set `NEMO_ONLINE_TRAINING_ADMIN_TRAINING_RECORD_NAME` in settings.py to customize the training record model admin name. Default is "Training Record"

# Tests

To run the tests:
```bash
python run_tests.py
```
