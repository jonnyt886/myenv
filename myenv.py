#!/usr/bin/python3

"""myenv - your personal environment

myenv gives you control over your personal environment, allowing you
to customise PATH and symlinks in your home directory and keep the
underlying configuration in git, nicely tracked and version controlled.

usage: myenv <operation>

Operation can be one of:
  create <profilename>
  edit <profilename>
      Create a new profile directory and open up its `profile.json`
      file in an editor. When `create` is specified, if the profile
      already exists, an error will occur.

  install
      Install the current profile.

      "Install" currently means creating the symlinks configured in
      the profile's `profile.json` in your home directory.

  profile
      This is designed to be called by your shell when you login; it
      finds all myenv profiles to activate and installs them. You should
      call it from your ~/.bash_profile, ~/.zprofile or ~/.profile.


PROFILES
A profile is just a collection of files with a `profile.json` file.
You can use a profile for whatever you like; the `profile.json` adds
a few useful features that myenv uses:
  - `symlinks` allows you to set up symlinks in your $HOME that point to
      files in your profile directory, when `myenv install` is called.
      I use this to keep files like .vimrc and my Openbox rc.xml in my
      profile (and thus in version control etc). It means that on any
      machine I own I can checkout my myenv repo and immediately inherit
      all the configuration I want.
  - `selectors` allow you to select your profile based on the existence
      of a file on your filesystem, or on your username or hostname.
      This is handy if you have your myenv git repository checked out on
      more than one machine, or more than one user account, and you want
      to use a different profile automagically based on some sort of
      context. You may also only want to enable a profile (e.g. your 'dev'
      profile) if certain files/directories exist (e.g. ~/git exists with
      all your repos and code). See SELECTORS, below, for more info.
  - `path` allows you to add particular directories in your profile to
      your PATH. myenv makes this work by symlinking `~/.profile` to a
      script that reads your `profile.json`.
  - `env` allows you to set up other environment variables according to
      your needs (e.g. EDITOR, HTTP_PROXY, PYTHONPATH, etc).
  - `onlogin` allows you to run scripts when you login and your profile
      is first loaded. I recommend you use the more standard configuration
      for this (e.g. ~/.config/autostart/ or ~/.config/openbox/autostart)
      but this might have some uses in certain cases, particularly if you
      don't use a graphical desktop.

All these features are implemented by plugins; for a full list of plugins,
see below.

SELECTORS
Selectors allow you to configure when your profile is active and when it
is not. You configure them via the profile.json file like this:

    {
      "selectors" : {
          "cmd": "test -f ~/.gitconfig"
      }   
    }

The example above will activate the profile if ~/.gitconfig exists. You
can actually achieve the same thing with:
    {
      "selectors" : {
          "file": "~/.gitconfig"
      }   
    }

The current selectors are supported:
    "cmd"   runs the specified command; if the exit code is zero, the command
            is deemed to have succeeded and the profile is activated.

    "dir"   if the specified directory exists, the profile is activated.

    "file"  if the specified file exists, the profile is activated.

    "and"   only selects if all the specified subselectors are active

    "or"    selects if any of the specified subselectors are active

    "not"   selects if the specified sub-selector is *not* active

PLUGINS
Plugins implement the core functionality of myenv. They're activated by 
specifying them in your profile.json file. The following plugins can be used:
    "symlinks"  creates a symlink for each source/destination pair specified;
                existing files will be overwritten!

    "copies"    copies all files for each source/destination pair specified

    "env"       sets environment variables
"""


# beginning of code #

# note on imports - this script must be entirely self-standing, i.e. have
# no dependencies beyond the Python3 core API
import os, sys, shutil, json, subprocess
from os.path import (join, exists, lexists, isfile, isdir, islink, dirname)
import socket

# Dict of profiles (profile name -> RemoteProfile instance)
profiles = {}

# A few other general variables (populated later)
profile_dir = None
home = None

# add dicts together (d2 takes precedence over d1)
def add_dicts(*dd):
    result = {}

    for d in dd:
        for k,v in d.items():
            result[k] = v

    return result

# Represents a 'profile' for remote/
# name        the name of the profile (should correspond to the profile directory)
# symlinks    Names of symlinks to create for this remote/ dir. Mapping is 'path' -> 'linkname'
#            where path is the name of the file/dir in remote/ and 'linkname' is the name of the 
#            link created in the user's homedir.
# copies    Names of files to copy for this remote/ dir. Used mainly in place of symlinks for
#            apps that don't support symlinks (when running under Cygwin on Windows boxes).
#             Mapping is 'path' -> 'copyname' where 'path' is the name of
#             the file in remote/ and 'copyname' is the name of the copied file in the user's homedir.
class RemoteProfile:
    def __init__(self, profiledir):
        jsonfile = join(profiledir, 'profile.json')
        if not os.path.isfile(jsonfile):
            raise OSError(jsonfile+' does not exist')

        with open(jsonfile, 'r') as f:
            self.json = json.load(f)
            self.name = os.path.basename(profiledir)
            #self.copies = j.get('copies', {})

            self.selector = None
            selectorJson = self.json.get('selectors', None)
            if selectorJson != None:
                self.selector = create_selectors(selectorJson)
                
        self.path = profiledir

#    # Get all copies for this profile and any parent profiles
#    # Returns a dict of target file (relative to user's home) -> full-path-of-source-file
#    def get_all_copies(self):
#        result = self.get_copies()
#
#        if self.parent != None:
#            parent_result = self.parent.get_all_copies()
#            result = add_dicts(parent_result, result)
#
#        return result
#
#    # Get all symlinks for this profile and any parent profiles
#    # Returns a dict of target file -> source-file
#    #   note: paths should be ABSOLUTE
#    def get_all_symlinks(self):
#        result = self.get_symlinks()
#
#        if self.parent != None:
#            parent_result = self.parent.get_all_symlinks()
#
#            # put result second, so that its values take precedence
#            result = add_dicts(parent_result, result)
#
#        return result
#
    def __repr__(self):
        return self.name

class Selector(object):
    """Defines a selector, which can be used by profiles to change
    when they're active and when they're not."""
    
    def __init__(self, config):
        """Initialise the selector; <config> is the content of the
        JSON element that created this selector."""
        self.config = config

    def is_active(self):
        """Function to determine whether the selector is active or 
        not. Subclasses should override this."""
        return True

class HostSelector(Selector):
    """Selects based on hostname. Supports matching on hostname
    (with DNS domain), e.g. "host.example.com", or an entire domain,
    e.g. ".example.com". You can specify multiple hostnames/
    domainnames using a JSON array."""

    def is_active(self):
        if type(self.config) is str:
            hosts = [ self.config ]
        elif type(self.config) is list:
            hosts = self.config
        else:
            raise ValueError('invalid value for "host" selector; \
                you need to specify a string, or an array')

        fqdn = socket.getfqdn().lower()
        dotidx = fqdn.find('.')

        if dotidx == -1:
            hostname = fqdn
        else:
            hostname = fqdn[0:dotidx]

        # exact match
        for host in hosts:
            if host == '*':
                return True
            elif host == fqdn:
                return True
            elif host == hostname:
                return True

            # fuzzy match
            elif host.startswith('.') and fqdn.endswith(host):
                # e.g. '.example.com'
                return True

        return False


    def __repr__(self):
        return 'HostSelector('+self.config+')'

class DirSelector(Selector):
    """Select based on the existence of a directory. Config should
    be a string containing directory name. You can use environment
    variables or ~ when specifying the directory."""
    def is_active(self):
        if type(self.config) is str:
            _dir = self.config
        else:
            raise ValueError('invalid value for "dir" selector; \
                you need to specify a string')

        _dir = expand(_dir)
        return os.path.isdir(_dir)

    def __repr__(self):
        return 'DirSelector('+self.config+')'

class FileSelector(Selector):
    """Select based on the existence of a file. Config should
    be a string containing file name. You can use environment
    variables or ~ when specifying the file."""
    def is_active(self):
        if type(self.config) is str:
            _file = self.config
        else:
            raise ValueError('invalid value for "dir" selector; \
                you need to specify a string')

        _file = expand(_file)
        return os.path.isfile(_file)

    def __repr__(self):
        return 'FileSelector('+self.config+')'

class AndSelector(Selector):
    """Select based on other selectors matching - all nested selectors
    must match. Config should be the entire subselector config as if 
    it were specified as a top-level selector. For example:
    {
        "selectors": {
            "and" : {
                "file": "~/marker_file",
                "host": "mybox"
            }
        }
    }
    """
    def is_active(self):
        if type(self.config) is dict:
            subselectors = self.config
        else:
            raise ValueError('invalid value for "and" selector; \
                you need to specify a dict')
        
        subselectors = create_selectors(subselectors)

        for selector in subselectors:
            if not selector.is_active():
                return False

        return True

    def __repr__(self):
        return 'AndSelector('+self.config+')'

class OrSelector(Selector):
    """Select based on other selectors matching - any nested selector
    can match. Config should be the entire subselector config as if 
    it were specified as a top-level selector. For example:
    {
        "selectors": {
            "or" : {
                "file": "~/marker_file",
                "host": "mybox"
            }
        }
    }
    """
    def is_active(self):
        if type(self.config) is dict:
            subselectors = self.config
        else:
            raise ValueError('invalid value for "or" selector; \
                you need to specify a dict')
        
        subselectors = create_selectors(subselectors)

        for selector in subselectors:
            if selector.is_active():
                return True

        return False

    def __repr__(self):
        return 'OrSelector('+self.config+')'

class NotSelector(Selector):
    """Select based on another selectors not matching. Config should
    be the entire subselector config as if it were specified as a 
    top-level selector. You can only specify one selector. For example:
    {
        "selectors": {
            "not" : {
                "file": "~/marker_file"
            }
        }
    }
    """
    def is_active(self):
        if type(self.config) is dict:
            subselectors = self.config
        else:
            raise ValueError('invalid value for "not" selector; \
                you need to specify a dict')

        if len(subselectors.items()) > 1:
            raise ValueError('invalid value for "not" selector; \
                you can only specify one selector; use "and" or "or" \
                to specify several')
        
        subselectors = create_selectors(subselectors)

        return not subselectors[0].is_active()

    def __repr__(self):
        return 'NotSelector('+str(self.config)+')'

class Plugin(object):
    """Defines a plugin for use by profiles."""

    def beforeInstall(self):
        """Run immediately before `install` is run for all profiles."""
        pass

    def install(self, profiles):
        """When the user invokes `myenv install`, this function is called
        with all active profiles passed in."""
        pass

    def generateDotProfile(self, profiles):
        """When `myenv profile` is invoked, this function is called with all
        active profiles passed in.

        This function should return a string (or list of strings) containing
        shell commands that will be executed by the user's shell when they
        login. This function is called, and the commands evaluated, as part
        of the login process and so should (a) be fast and (b) be safe.

        Additionally, commands should be POSIX compliant to ensure they will
        work with the maximum number of shells and user setups."""
        pass

class SymlinksPlugin(Plugin):
    def get_symlinks(self, profile):
        """Get all symlinks for profile (full paths)
        Returns a dict of target file -> source-file
          note: paths should be ABSOLUTE"""
        result = {}
        symlinks = profile.json.get('symlinks', {})
        for k, v in symlinks.items():
            kk = expand(k)
            if not os.path.isabs(kk): kk = join(home, kk)
            vv = join(profile.path, expand(v))

            if not os.path.exists(vv):
                raise OSError(v+' is defined in profile '+profile.name+' but does not exist')

            if os.path.realpath(kk) == home:
                raise OSError(kk+' points to your entire home directory (defined in profile '+profile.name+')')

            if not os.path.isabs(kk):
                result[kk] = vv
            else:
                # if they specified an absolute path that's fine but
                # ensure that it is within the user's homedir
                if not kk.startswith(home):
                    raise OSError('symlink '+k+' in profile '+profile.name+' is not inside $HOME')

                result[kk] = vv

        return result 

    def find_symlinks(self, directory, targetdir):
        """Finds all symlinks in the given directory that point to paths
        beneath targetdir. Doesn't search subdirs."""
        result = []

        files = os.listdir(directory)
        for file in files:
            filepath = join(directory, file)

            if os.path.islink(filepath):
                linktarget = os.readlink(filepath)

                if linktarget.startswith(targetdir):    
                    result.append(file)
        return result

    def beforeInstall(self):
        # first look for symlinks in $HOME that point to files in profile_dir
        for f in self.find_symlinks(home, profile_dir):
            symlink_path = join(home, f)
            if lexists(symlink_path):
                os.remove(symlink_path)
        
    def install(self, profiles):
        for profile in profiles:
            self.installProfile(profile)

    def installProfile(self, profile):
        """Re-creates symlinks for the given profile."""
        # nb all paths in this dict will be absolute
        new_symlinks = self.get_symlinks(profile)

        # now look for symlinks configured in the profile that exist
        # if the target symlink exists, check that its type (file/dir)
        # is the same as the file that it is pointing to
        for target, source in new_symlinks.items():
            # lexists == True for symlinks that exist but are broken
            if lexists(target):
                if isdir(target):
                    if not isdir(source):
                        raise OSError(target+' is a directory but source file in profile '+
                            profile.name+' is not')
                    #shutil.rmtree(target)
                    os.remove(target) # it's still a symlink so don't rmtree()
                
                elif isfile(target):
                    if not isfile(source):
                        raise OSError(target+' is a directory but source file in profile '+
                            profile.name+' is not')
                    os.remove(target)
                
                else:
                    raise OSError('unknown filetype: '+target)
        
        for target, source_file in new_symlinks.items():
            dest_file = join(home, target)

            if not exists(source_file):
                print('Warning: source file ' + source_file + 
                    ' does not exist (creating symlink to it anyway)', file=sys.stderr)

            try:
                os.symlink(source_file, dest_file)
            except OSError as ex:
                print('Error while creating', dest_file + ':', str(ex), file=sys.stderr)

# TODO TODO TODO TODO
# TODO TODO TODO TODO
# TODO TODO TODO TODO
# TODO TODO TODO TODO
class CopiesPlugin(Plugin):
    def get_copies(self, profile):
        """Get all copies for this profile (full paths)
        Returns a dict of target file (relative to user's home) -> 
            full-path-of-source-file"""
        result = {}
        copies = profile.json.get('copies', {})
        for k, v in copies.items():
            result[v] = join(profile.path, k)
        return result 


    # Re-creates copied files for the given profile
    def do_copies(self, profile):
        new_copies = self.get_copies(profile)

        for v in list(new_copies.keys()):
            vpath = join(home, v)
            if exists(vpath):
                if isfile(vpath) or islink(vpath):
                    os.remove(vpath)
                elif isdir(vpath):
                    shutil.rmtree(vpath)
                else:
                    raise OSError(str(src) + ' - must be a file or dir')

        for target, src in new_copies.items():
            try:
                dst = join(home, target)

                if isfile(src):
                    target_dir = dirname(dst)
                    if not exists(target_dir):
                        os.mkdir(target_dir)

                    shutil.copy2(src, dst)

                elif isdir(src):
                    shutil.copytree(src, dst, symlinks = True)

                else:
                    raise OSError(str(src) + ' - must be a file or dir to copy')

            except OSError as ex:
                print('Error while creating', join(home, target) + ':', str(ex), file=sys.stderr)

class EnvPlugin(Plugin):
    def generateDotProfile(self, profiles):
        # As multiple profiles may set the same env var,
        # we need to co-ordinate a bit; ret is a dict
        # of var name -> var value(s). var value can either
        # be a str or a list.
        #
        # If a profile specifies a var value as a string, this
        # is assumed *not* to be a path, and we assume that the
        # variable is intended to only hold one value, therefore
        # if several profiles set the variable the last one
        # wins and overwrites previous values.
        #
        # If a profile specifies a var value as  a list, we
        # assume that the variable can hold multiple values
        # (separated by ':' as usual) and that each value is
        # a path. In this case, if several profiles set values
        # for the variable, each value is *added* to the list.
        ret = {}

        for profile in profiles:
            env = profile.json.get('env', {})

            for k, v in env.items():
                # k is varname, v is value (v might be a list)
                print('envp %s %s=%s'%(profile.name, k, str(v)), file=sys.stderr)
                
                if type(v) is str:
                    if k in ret and type(ret[k]) is not str:
                        raise ValueError('profile %s specified enviroment variable "%s" '+
                                'as a string but it should be a list' % (profile.name, k))
                    ret[k] = v

                elif type(v) is list:
                    new_v = []

                    for vv in v:
                        # if v is a list, assume a list of paths
                        vv = expand(vv)

                        if not os.path.isabs(vv):
                            # assume relative to profile dir
                            vv = os.path.join(profile.path, vv)

                        new_v.append(vv)

                    if k in ret:
                        if type(ret[k]) is not list:
                            raise ValueError('profile %s specified enviroment variable "%s" '+
                                    'as a list but it should be a string' % (profile.name, k))
                        ret[k].extend(new_v)

                    else:
                        ret[k] = new_v
                    
                else:
                    raise ValueError('value for environment variable '+v+
                        ' is invalid; should be a string or list')

        rets = [] # list of `export` statements as strings
        for k, v in ret.items():
            if type(ret[k]) is list:
                if k in os.environ:
                    rets.append('export %s=%s:%s' % (k, os.environ[k], ':'.join(v)))
                else:
                    rets.append('export %s=%s' % (k, ':'.join(v)))
            else:
                rets.append('export %s=%s' % (k, v))

        return rets


def expand(s):
    return os.path.expanduser(os.path.expandvars(s))

def create_selectors(json):
    """Parses the given JSON (which should be the value of the 
    "selectors" property in a profile JSON) and creates selector
    instances on the profile."""
    SELECTOR_MAPPINGS = {
        "host": HostSelector,
        "dir": DirSelector,
        "file": FileSelector,
        "and": AndSelector,
        "not": NotSelector,
        "or": OrSelector,
    }

    ret = []

    # json should be a dict
    for (k, v) in json.items():
        if not k in SELECTOR_MAPPINGS:
            raise ValueError('unknown selector: '+k)

        selClass = SELECTOR_MAPPINGS[k]
        ret.append(selClass(v))

    return ret

# Used to add items to a nested dictionary:
# dict1{ k: dict2{k2:v} }
def add_to_dict(d, k, k2, v):
    if not k in d:
        d[k] = {}
    
    d[k][k2] = v

# Cygwin-friendly way to get the path to the user's home directory
def get_home():
    result = None

    if 'HOME' in os.environ:
        result = os.environ['HOME']
    elif 'USERPROFILE' in os.environ:
        result = os.environ['USERPROFILE']
    else:
        result = None
        
    return result.strip()

def strip_trailing_backslash(str):
    return str.rstrip(' /')

# Add a new profile to the profiles list
def add_profile(profile):
    profiles[profile.name] = profile

def select_profiles():
    """Figure out which profiles we should use, based on selectors.
    First we try an exact match - if we don't get anything then we 
    try a 'fuzzy' match."""
    ret = []

    for (name, profile) in profiles.items():
        if profile.selector == None:
            # no selector means always activate
            ret.append(profile)

        else:
            add_it = True # only add if all selectors match
            for selector in profile.selector:
                if not selector.is_active():
                    add_it = False
                    break

            if add_it:
                ret.append(profile)

    return ret

def usage_and_exit():
    print('Usage:', sys.argv[0], ' <install|profile>', file=sys.stderr)
    sys.exit(1)


ACTIVE_PLUGINS = [
    SymlinksPlugin(),
    CopiesPlugin(),
    EnvPlugin(),
]
def runPluginBeforeInstall():
    for p in ACTIVE_PLUGINS:
        p.beforeInstall()

def runPluginInstall(profiles):
    for p in ACTIVE_PLUGINS:
        p.install(profiles)

def runPluginGenerateDotProfile(profiles):
    ret = []
    for p in ACTIVE_PLUGINS:
        r = p.generateDotProfile(profiles)
        if r is not None: ret.append(r)
    return ret
 
#
# Script starts...
#

profile_dir = expand('~/.myenv')
if not os.path.exists(profile_dir):
    print('creating profile directory '+profile_dir)
    os.mkdir(profile_dir)

for f in os.listdir(profile_dir):
    ffull = join(profile_dir, f)
    if isdir(ffull) and isfile(join(ffull, 'profile.json')):
        p = RemoteProfile(ffull)
        add_profile(p)

profiles = select_profiles()
print('Active profiles', profiles, file=sys.stderr)

# Assert that the script is run from ~/remote/
script_abs_path = os.path.abspath(join(profile_dir, '..')).strip()

# Use realpath() to resolve any symlinks so that we are
# comparing two absolute paths
home = os.path.realpath(get_home())

if not script_abs_path.startswith(home):
    print('This installer should be within a directory in your home directory', file=sys.stderr)
    print('(which is', strip_trailing_backslash(script_abs_path) + ', not', strip_trailing_backslash(home) + ')', file=sys.stderr)
    exit(2)

if len(sys.argv) < 2:
    usage_and_exit()

elif sys.argv[1] == 'create' or sys.argv[1] == 'edit':
    profileName = sys.argv[2]
    profilePath = join(profile_dir, profileName)
    profileJsonPath = join(profilePath, 'profile.json')

    if not os.path.exists(profilePath):
        os.mkdir(profilePath)
        with open(profileJsonPath, 'w') as f:
            f.write('{\n}\n');

    editor = 'nano'
    if 'EDITOR' in os.environ: editor = os.environ['EDITOR']
    print('running',editor+' '+profileJsonPath)
    subprocess.call(editor+' '+profileJsonPath, shell=True)

elif sys.argv[1] == 'install':
    # given a current env installation, apply symlinks from the current profile
    # to the user's home directory
    runPluginBeforeInstall()
    runPluginInstall(profiles)

elif sys.argv[1] == 'profile':
    ret = runPluginGenerateDotProfile(profiles)

    # https://stackoverflow.com/a/11264751/1432488
    rret = [val for sublist in ret for val in sublist]
    [print(r) for r in rret]

else:
       usage_and_exit()
