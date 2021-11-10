# Copyright 2021 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Package Setup script for TensorFlow GNN."""

import os
import platform
import subprocess
import sys

import setuptools
from setuptools import find_packages
from setuptools import setup
from setuptools.command.install import install
from setuptools.dist import Distribution
# pylint:disable=g-bad-import-order
# setuptools must be imported prior to distutils.
from distutils import spawn
from distutils.command import build
# pylint:enable=g-bad-import-order


class _BuildCommand(build.build):
  """Build everything needed to install.

  This overrides the original distutils "build" command to to run bazel_build
  command instead, before any sub_commands. This is convenient in order to
  generate protocol buffer files and eventually also build C++ extension
  modules.

  The build command is also invoked from bdist_wheel and install command,
  therefore this implementation covers the following commands:

    - pip install . (which invokes bdist_wheel)
    - python setup.py install (which invokes install command)
    - python setup.py bdist_wheel (which invokes bdist_wheel command)

  """

  def _build_cc_extensions(self):
    return True

  # Add the "bazel_build" command as the first sub-command of "build". Each
  # sub_command of "build" (e.g. "build_py", "build_ext", etc.) is executed
  # sequentially when running a "build" command, if the second item in the tuple
  # (predicate method) is evaluated to true.
  sub_commands = [
      ('bazel_build', _build_cc_extensions)] + build.build.sub_commands


class _BazelBuildCommand(setuptools.Command):
  """Build C++ extensions and public protos with Bazel.

  Running this command will populate the *_pb2.py files next to your *.proto
  files.
  """

  def initialize_options(self):
    pass

  def finalize_options(self):
    self._bazel_cmd = spawn.find_executable('bazel')
    if not self._bazel_cmd:
      raise RuntimeError(
          'Could not find "bazel" binary. Please visit '
          'https://docs.bazel.build/versions/master/install.html for '
          'installation instruction.')
    self._additional_build_options = []
    if platform.system() == 'Darwin':
      self._additional_build_options = ['--macos_minimum_os=10.9']
    elif platform.system() == 'Windows':
      self._additional_build_options = ['--copt=-DWIN32_LEAN_AND_MEAN']

  def run(self):
    subprocess.check_call(
        [self._bazel_cmd,
         'run', '-c', 'opt', '--experimental_repo_remote_exec'] +
        self._additional_build_options +
        ['//package:move_generated_files'],
        # Bazel should be invoked in a directory containing bazel WORKSPACE
        # file, which is the root directory.
        cwd=os.path.dirname(os.path.realpath(__file__)),
        env=os.environ.copy().update({'PYTHON_BIN_PATH': sys.executable}))


# TFDV is not a purelib. However because of the extension module is not built
# by setuptools, it will be incorrectly treated as a purelib. The following
# works around that bug.
class _InstallPlatlibCommand(install):

  def finalize_options(self):
    install.finalize_options(self)
    self.install_lib = self.install_platlib


class _BinaryDistribution(Distribution):
  """This class is needed in order to create OS specific wheels."""

  def is_pure(self):
    return False

  def has_ext_modules(self):
    return True


def select_constraint(default, nightly=None, git_master=None):
  """Select dependency constraint based on TFX_DEPENDENCY_SELECTOR env var."""
  selector = os.environ.get('TFX_DEPENDENCY_SELECTOR')
  if selector == 'UNCONSTRAINED':
    return ''
  elif selector == 'NIGHTLY' and nightly is not None:
    return nightly
  elif selector == 'GIT_MASTER' and git_master is not None:
    return git_master
  else:
    return default


def get_version():
  """Get version from version module."""
  version_path = os.path.join(os.path.dirname(__file__), 'tensorflow_gnn')
  sys.path.insert(0, version_path)
  # pytype: disable=import-error  # pylint: disable=g-import-not-at-top
  from version import __version__ as v
  return v


# Get the long description from the README file.
with open('README.md') as fp:
  _LONG_DESCRIPTION = fp.read()


console_scripts = [
    'tensorflow_gnn.tools.generate_training_data',
    'tensorflow_gnn.tools.print_training_data',
    'tensorflow_gnn.tools.sampled_stats',
    'tensorflow_gnn.tools.validate_graph_schema',
]


setup(
    name='tensorflow-gnn',
    version=get_version(),
    author='Google LLC',
    # TODO(blais): Create an appropriately named external group, e.g.,
    # tensorflow-gnn@
    author_email='graph-learning-team@googlegroups.com',
    license='Apache 2.0',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'Intended Audience :: Science/Research',
        'License :: OSI Approved :: Apache Software License',
        'Operating System :: MacOS :: MacOS X',
        'Operating System :: POSIX :: Linux',
        'Operating System :: Microsoft :: Windows',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3 :: Only',
        'Topic :: Scientific/Engineering',
        'Topic :: Scientific/Engineering :: Artificial Intelligence',
        'Topic :: Scientific/Engineering :: Mathematics',
        'Topic :: Software Development',
        'Topic :: Software Development :: Libraries',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
    namespace_packages=[],
    # Make sure to sync the versions of common dependencies (absl-py, numpy,
    # six, and protobuf) with TF.
    install_requires=[
        'absl-py',
        'apache-beam[gcp]>=2.32',
        'grpcio',
        'matplotlib',
        'mock',
        'networkx',
        'numpy',
        'protobuf>=3.17',
        'pyarrow',
        'pygraphviz',
        'scipy',
        'six',
        'tf-nightly-cpu>=2.7.0.dev20210908',
    ],
    python_requires='>=3.9,<4',
    packages=find_packages(),
    include_package_data=True,
    package_data={'': ['*.proto']},
    zip_safe=False,
    distclass=_BinaryDistribution,
    description='A library for building scalable graph neural networks in TensorFlow.',
    long_description=_LONG_DESCRIPTION,
    long_description_content_type='text/markdown',
    keywords='tensorflow gnn graph',
    # TODO(blais): Associate a public URL for the project, e.g.,
    # url=https://www.tensorflow.org/gnn.
    # TODO(blais): Associate a public download URL for the project, e.g.,
    # https://github.com/tensorflow/gnn/tags.
    download_url='https://github.com/tensorflow/gnn.git',
    requires=[],
    cmdclass={
        'install': _InstallPlatlibCommand,
        'build': _BuildCommand,
        'bazel_build': _BazelBuildCommand,
    },
    entry_points={
        'console_scripts': [
            'tfgnn_{}={}:main'.format(libname.split('.')[-1], libname)
            for libname in console_scripts
        ],
    }
)
