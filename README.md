# myenv
Manage and customise environment variables, dotfiles, etc, across systems.

`myenv` gives you control over your personal environment, allowing you to customise environment variables (like `PATH`) and symlink your dotfiles in your home directory and keep the underlying configuration in `git`, nicely tracked and version controlled.

`myenv` uses `~/.myenv` as its configuration directory, and in there you set up profiles which contain your files and configuration. You can have your profiles do anything you like, and multiple profiles can be active or inactive on the system you're using depending on selectors you define (e.g. enable a profile based on a directory existing, or the system having a certain hostname). Use `profile.json` to configure each profile.

`myenv` is Python, and requires Python 3.3+.

How can `myenv` help you? Well, if you use more than one system and want to sync your configuration between them, and some of those systems may have different purposes. For example, with `myenv` I can:
- symlink `tmux.conf`, my Openbox settings and `.zshrc` on all systems
- enable my cloud SSH keys only on my dev box
- set up my PATH to include scripts in my local git repo at `~/git` if that directory exists
- set up my GitHub credentials only if I have GitHub projects checked out at `~/github`

## Usage
Usage: `myenv <operation>`

Operation can be one of:
-  `create <profilename>`
-  `edit <profilename>` Create a new profile directory and open up its `profile.json` file in an editor. When `create` is specified, if the profile already exists, an error will occur.

-  `install` Install the current profile. "Install" currently means creating the symlinks configured in
      the profile's `profile.json` in your home directory.

-  `profile` This is designed to be called by your shell when you login; it finds all myenv profiles to activate and installs them. You should call it from your ~/.bash_profile, ~/.zprofile or ~/.profile (make sure you use `eval`, for example `eval ``myenv profile```)

## Profiles
A profile is just a collection of files with a `profile.json` file. Here's an example of `profile.json`:

	{
		"symlinks": {
			"~/.config/openbox": "openbox",
			"~/.oh-my-zsh/custom/jonny.zsh": "zshrcc",
			"~/.zshrc": "zshrc",
			"~/.ssh/config": "ssh_config",
			"~/.tmux.conf": "tmux.conf"
		},
		"env": {
			"PATH": [
				"bin"
			]
		},
		"selectors": {
			"or": {
				"host": [
					"vaio"
				]
			}
		}
	}

You can use a profile for whatever you like; the `profile.json` adds a few useful features that myenv uses:
  - `symlinks` allows you to set up symlinks in your `$HOME` that point to files in your profile directory, when `myenv install` is called.  I use this to keep files like `.vimrc` and my Openbox `rc.xml` in my profile (and thus in version control etc). It means that on any machine I own I can checkout my myenv repo and immediately inherit all the configuration I want.
  - `copies` is exactly like `symlinks` but copies files instead of symlinking them; only really useful in my experience if you're on Cygwin.
  - `selectors` allow you to select your profile based on the existence of a file on your filesystem, or on your username or hostname.  This is handy if you have your myenv git repository checked out on more than one machine, or more than one user account, and you want to use a different profile automagically based on some sort of context. You may also only want to enable a profile (e.g. your 'dev' profile) if certain files/directories exist (e.g. `~/git` exists with all your repos and code). See SELECTORS, below, for more info. Remember that more than one profile can be active at once.
  - `path` allows you to add particular directories in your profile to your `PATH`. myenv makes this work by symlinking `~/.profile` to a script that reads your `profile.json`.
  - `env` allows you to set up other environment variables according to your needs (e.g. `EDITOR`, `HTTP_PROXY`, `PYTHONPATH`, etc).

All these features are implemented by plugins; for a full list of plugins, see below.

## Selectors
Selectors allow you to configure when your profile is active and when it is not.

### File-based
Only selects a profile if a file exists. Example:
    {
        "selectors" : {
            "file": "~/.gitconfig"
        }   
    }

You can use environment variables too; this is equivalent:
    {
        "selectors" : {
            "file": "$HOME/.gitconfig"
        }   
    }

### Directory based
Select only if a directory exists. Example:
    {
        "selectors" : {
            "dir": "~/git"
        }   
    }

### Host-name based
Select only if the current system has a hostname/domain matches. Hostname example:
    {
        "selectors" : {
            "host": "alphabox"
        }   
    }

Domain example (matches anything inside **example.com**):
    {
        "selectors" : {
            "host": ".example.com"
        }   
    }

You can have several matches as an array; if any of these match, the selector is active:
    {
        "selectors" : {
            "host": [
                ".example.com",
                "alphabox"
            ]
        }   
    }

### Logical operators
You can mix and match selectors using AND, OR and NOT semantics, all specified as JSON.

For example:
    {
        "selectors" : {
            "or": {
                "file": "~/.gitconfig",
                "dir": "~/.git"
            }
        }
    }

    {
        "selectors" : {
            "and": {
                "host": "alphabox",
                "not": {
                    "host": ".baddomain.com"
                }
            }
        }
    }

