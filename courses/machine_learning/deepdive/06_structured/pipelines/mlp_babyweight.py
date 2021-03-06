#!/usr/bin/env python3
# Copyright 2018 Google LLC
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


import kfp.dsl as dsl

# FIXME: https://github.com/kubeflow/pipelines/pull/212
# will allow me to import this as
#     from kfp.dsl.components import kubeflow_tfjob_launcher_op
def kubeflow_tfjob_launcher_op(container_image, command, number_of_workers: int, number_of_parameter_servers: int,
                               tfjob_timeout_minutes: int, output_dir=None, step_name='TFJob-launcher'):
  return dsl.ContainerOp(
    name=step_name,
    image='gcr.io/ml-pipeline/ml-pipeline-kubeflow-tf:0.1.0',
    arguments=[
                '--workers', number_of_workers,
                '--pss', number_of_parameter_servers,
                '--tfjob-timeout-minutes', tfjob_timeout_minutes,
                '--container-image', container_image,
                '--output-dir', output_dir,
                '--ui-metadata-type', 'tensorboard',
                '--',
              ] + command,
    file_outputs={'train': '/output.txt'}
  )


class ObjectDict(dict):
  def __getattr__(self, name):
    if name in self:
      return self[name]
    else:
      raise AttributeError("No such attribute: " + name)


@dsl.pipeline(
  name='babyweight',
  description='Train Babyweight model'
)
def train_and_deploy(
    project=dsl.PipelineParam(name='project', value='cloud-training-demos'),
    bucket=dsl.PipelineParam(name='bucket', value='cloud-training-demos-ml'),
    startYear=dsl.PipelineParam(name='startYear', value='2000')
):
  """Pipeline to train babyweight model"""
  start_step = 3

  # Step 1: create training dataset using Apache Beam on Cloud Dataflow
  if start_step <= 1:
    preprocess = dsl.ContainerOp(
      name='preprocess',
      # image needs to be a compile-time string
      image='gcr.io/cloud-training-demos/babyweight-pipeline-bqtocsv:latest',
      arguments=[
        '--project', project,
        '--mode', 'cloud',
        '--bucket', bucket,
        '--start_year', startYear
      ],
      file_outputs={'bucket': '/output.txt'}
    )
  else:
    preprocess = ObjectDict({
      'outputs': {
        'bucket': bucket
      }
    })

  # Step 2: Do hyperparameter tuning of the model on Cloud ML Engine
  if start_step <= 2:
    hparam_train = dsl.ContainerOp(
      name='hypertrain',
      # image needs to be a compile-time string
      image='gcr.io/cloud-training-demos/babyweight-pipeline-hypertrain:latest',
      arguments=[
        preprocess.outputs['bucket']
      ],
      file_outputs={'jobname': '/output.txt'}
    )
  else:
    hparam_train = ObjectDict({
      'outputs': {
        'jobname': 'babyweight_181008_210829'
      }
    })

  # Step 3: Train the model some more, but on the pipelines cluster itself
  if start_step <= 3:
    # train: /output.txt is the model directory
    train_tuned = kubeflow_tfjob_launcher_op(
      container_image='gcr.io/cloud-training-demos/babyweight-pipeline-traintuned-trainer:latest',
      command=[ # replaces the ENDPOINT of container
        'bash',
        '/babyweight/src/train.sh',
        hparam_train.outputs['jobname'],
        bucket
      ],
      number_of_workers=10,
      number_of_parameter_servers=3,
      tfjob_timeout_minutes=5,
      step_name='traintuned'
    )
  else:
    train_tuned = ObjectDict({
        'outputs': {
          'train': 'gs://cloud-training-demos-ml/babyweight/hyperparam/15'
        }
    })

  # Step 4: Deploy the trained model to Cloud ML Engine
  if start_step <= 4:
    deploy_cmle = dsl.ContainerOp(
      name='deploycmle',
      # image needs to be a compile-time string
      image='gcr.io/cloud-training-demos/babyweight-pipeline-deploycmle:latest',
      arguments=[
        train_tuned.outputs['train'],  # modeldir
        'babyweight',
        'mlp'
      ],
      file_outputs={
        'model': '/model.txt',
        'version': '/version.txt'
      }
    )
  else:
    deploy_cmle = ObjectDict({
      'outputs': {
        'model': 'babyweight',
        'version': 'mlp'
      }
    })

  # Step 4: Deploy the trained model to Cloud ML Engine
  if start_step <= 5:
    deploy_cmle = dsl.ContainerOp(
      name='deployapp',
      # image needs to be a compile-time string
      image='gcr.io/cloud-training-demos/babyweight-pipeline-deployapp:latest',
      arguments=[
        deploy_cmle.outputs['model'],
        deploy_cmle.outputs['version']
      ],
      file_outputs={
        'appurl': '/appurl.txt'
      }
    )
  else:
    deploy_cmle = ObjectDict({
      'outputs': {
        'appurl': 'https://cloud-training-demos.appspot.com/'
      }
    })


if __name__ == '__main__':
  import kfp.compiler as compiler

  compiler._compile(train_and_deploy, __file__ + '.tgz')
