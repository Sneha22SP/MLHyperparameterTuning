{
 "cells": [
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "# Random Search\n",
    "\n",
    "## Introduction\n",
    "\n",
    "In This example of random search hyperparameter tuning we make use of the Batch AI extensions, including the JobFactory module to generate values for hyperparameters, and the ExperimentUtils module for bulk job submission.\n",
    "\n",
    "## Imports"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": 1,
   "metadata": {},
   "outputs": [],
   "source": [
    "from __future__ import print_function\n",
    "import sys\n",
    "import glob\n",
    "import azure.mgmt.batchai.models as models\n",
    "from azure.storage.blob import BlockBlobService\n",
    "from azure.storage.file import FileService\n",
    "sys.path.append('.')\n",
    "import utilities as utils\n",
    "from utilities.job_factory import ParameterSweep, NumericParameter, DiscreteParameter"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "### Read Configuration and Create Batch AI client"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": 2,
   "metadata": {
    "nbpresent": {
     "id": "bfa11f00-8866-4051-bbfe-a9646e004910"
    }
   },
   "outputs": [],
   "source": [
    "configuration_path = 'configuration.json'\n",
    "cfg = utils.config.Configuration(configuration_path)\n",
    "client = utils.config.create_batchai_client(cfg)"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "Create the resource group and Batch AI workspace if they do not exist."
   ]
  },
  {
   "cell_type": "code",
   "execution_count": 3,
   "metadata": {
    "scrolled": true
   },
   "outputs": [],
   "source": [
    "utils.config.create_resource_group(cfg)\n",
    "_ = client.workspaces.create(cfg.resource_group, cfg.workspace, cfg.location).result()"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "## 1. Prepare Training Dataset and Script in Azure Storage\n",
    "\n",
    "### Create Azure Blob Container\n",
    "\n",
    "We will create a new Blob Container with name `batchaisample` under your storage account. This will be used to store the  training datasets.\n",
    "\n",
    "**Note** You don't need to create new blob Container for every cluster. We are doing this in this sample to simplify resource management for you."
   ]
  },
  {
   "cell_type": "code",
   "execution_count": 4,
   "metadata": {},
   "outputs": [
    {
     "data": {
      "text/plain": [
       "True"
      ]
     },
     "execution_count": 4,
     "metadata": {},
     "output_type": "execute_result"
    }
   ],
   "source": [
    "azure_blob_container_name = 'batchaisample'\n",
    "blob_service = BlockBlobService(cfg.storage_account_name, cfg.storage_account_key)\n",
    "blob_service.create_container(azure_blob_container_name, fail_on_exist=False)"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "### Upload the datasets to Azure Blob Container\n",
    "\n",
    "We will upload the TSVs created by the [data prep notebook](00_Data_Prep.ipynb) to an Azure blob container directory named `dataset` using the Azure SDK for Python."
   ]
  },
  {
   "cell_type": "code",
   "execution_count": 5,
   "metadata": {},
   "outputs": [
    {
     "name": "stdout",
     "output_type": "stream",
     "text": [
      "questions.tsv\n",
      "balanced_pairs_train.tsv\n",
      "dupes_test.tsv\n",
      "dupes_train.tsv\n",
      "balanced_pairs_test.tsv\n"
     ]
    }
   ],
   "source": [
    "dataset_directory = 'dataset'\n",
    "dataset_files = glob.glob('*.tsv')\n",
    "for file in dataset_files:\n",
    "    print(file)\n",
    "    blob_service.create_blob_from_path(azure_blob_container_name, \n",
    "                                       dataset_directory + '/' + file,\n",
    "                                       file)"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "### Create Azure File Share\n",
    "\n",
    "For this example we will create a new File Share with name `batchaisample` under your storage account. This will be used to share the training script file created in the [create model notebook](01_Create_Model.ipynb), and also the output files created by the script.\n",
    "\n",
    "**Note** You don't need to create new file share for every cluster. We are doing this in this sample to simplify resource management for you."
   ]
  },
  {
   "cell_type": "code",
   "execution_count": 6,
   "metadata": {},
   "outputs": [
    {
     "data": {
      "text/plain": [
       "True"
      ]
     },
     "execution_count": 6,
     "metadata": {},
     "output_type": "execute_result"
    }
   ],
   "source": [
    "azure_file_share_name = 'batchaisample'\n",
    "file_service = FileService(cfg.storage_account_name, cfg.storage_account_key)\n",
    "file_service.create_share(azure_file_share_name, fail_on_exist=False)"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "Upload the training script to file share directory named `hyperparam_samples`."
   ]
  },
  {
   "cell_type": "code",
   "execution_count": 7,
   "metadata": {},
   "outputs": [],
   "source": [
    "script_path = 'hyperparam_samples'\n",
    "script_name = 'TrainTestClassifier.py'\n",
    "file_service.create_directory(\n",
    "    azure_file_share_name, script_path, fail_on_exist=False)\n",
    "file_service.create_file_from_path(\n",
    "    azure_file_share_name, script_path, script_name, script_name)"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "## 2. Create Azure Batch AI Compute Cluster\n",
    "\n",
    "### Configure Compute Cluster\n",
    "\n",
    "For this example we will use a cluster of `Standard_D4_v2` nodes. Number of nodes in the cluster is configured with `nodes_count` variable. We will call the cluster `d4`."
   ]
  },
  {
   "cell_type": "code",
   "execution_count": 8,
   "metadata": {},
   "outputs": [],
   "source": [
    "cluster_name = 'd4'\n",
    "nodes_count = 4\n",
    "vm_size = 'Standard_D4_v2'\n",
    "\n",
    "parameters = models.ClusterCreateParameters(\n",
    "    vm_size=vm_size,\n",
    "    scale_settings=models.ScaleSettings(\n",
    "        manual=models.ManualScaleSettings(target_node_count=nodes_count)\n",
    "    ),\n",
    "    user_account_settings=models.UserAccountSettings(\n",
    "        admin_user_name=cfg.admin,\n",
    "        admin_user_password=cfg.admin_password or None,\n",
    "        admin_user_ssh_public_key=cfg.admin_ssh_key or None,\n",
    "    )\n",
    ")"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "### Create Compute Cluster"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": 9,
   "metadata": {},
   "outputs": [],
   "source": [
    "_ = client.clusters.create(cfg.resource_group, cfg.workspace, cluster_name, parameters).result()"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "### Monitor Cluster Creation\n",
    "\n",
    "Monitor the just created cluster. The `utilities` module contains a helper function to print out detail status of the cluster."
   ]
  },
  {
   "cell_type": "code",
   "execution_count": 10,
   "metadata": {},
   "outputs": [
    {
     "name": "stdout",
     "output_type": "stream",
     "text": [
      "Cluster state: resizing Target: 4; Allocated: 0; Idle: 0; Unusable: 0; Running: 0; Preparing: 0; Leaving: 0\n"
     ]
    }
   ],
   "source": [
    "cluster = client.clusters.get(cfg.resource_group, cfg.workspace, cluster_name)\n",
    "utils.cluster.print_cluster_status(cluster)"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "## 3. Parameter Sweeping using Random Search\n",
    "Create a new experiment called ```random_search_experiment```."
   ]
  },
  {
   "cell_type": "code",
   "execution_count": 11,
   "metadata": {},
   "outputs": [],
   "source": [
    "experiment_name = 'random_search_experiment'\n",
    "experiment = client.experiments.create(cfg.resource_group, cfg.workspace, experiment_name).result()"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "Define specifications for the hyperparameters"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": 12,
   "metadata": {
    "scrolled": true
   },
   "outputs": [],
   "source": [
    "param_specs = [\n",
    "    DiscreteParameter(\n",
    "        parameter_name=\"ESTIMATORS\",\n",
    "        values=[1, 2]\n",
    "    ),\n",
    "    DiscreteParameter(\n",
    "        parameter_name=\"NGRAMS\",\n",
    "        values=[1, 2]\n",
    "    ),\n",
    "]"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "Create a parameter substitution object."
   ]
  },
  {
   "cell_type": "code",
   "execution_count": 13,
   "metadata": {},
   "outputs": [],
   "source": [
    "parameters = ParameterSweep(param_specs)"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "We will use the parameter substitution object to specify where we would like to substitute the parameters. We substitute\n",
    "the values for those parameters into `models.JobCreateParameters.cntk_settings.command_line_args`. Note that the `parameters` variable is used like a dict, with the `parameter_name` being used as the key to specify which parameter to substitute. When `parameters.generate_jobs` is called, the `parameters[name]` variables will be replaced with actual values."
   ]
  },
  {
   "cell_type": "code",
   "execution_count": 14,
   "metadata": {},
   "outputs": [],
   "source": [
    "azure_file_share_mount_path = 'afs'\n",
    "azure_blob_mount_path = 'bfs'\n",
    "jcp = models.JobCreateParameters(\n",
    "    cluster=models.ResourceId(id=cluster.id),\n",
    "    node_count=1,\n",
    "    std_out_err_path_prefix='$AZ_BATCHAI_JOB_MOUNT_ROOT/{0}'.format(azure_file_share_mount_path),\n",
    "    input_directories = [\n",
    "        models.InputDirectory(\n",
    "            id='SCRIPT',\n",
    "            path='$AZ_BATCHAI_JOB_MOUNT_ROOT/{0}/{1}'.format(azure_blob_mount_path, dataset_directory))\n",
    "    ],\n",
    "    output_directories = [\n",
    "        models.OutputDirectory(\n",
    "            id='ALL',\n",
    "            path_prefix='$AZ_BATCHAI_JOB_MOUNT_ROOT/{0}'.format(azure_file_share_mount_path))],\n",
    "    mount_volumes = models.MountVolumes(\n",
    "        azure_file_shares=[\n",
    "            models.AzureFileShareReference(\n",
    "                account_name=cfg.storage_account_name,\n",
    "                credentials=models.AzureStorageCredentialsInfo(\n",
    "                    account_key=cfg.storage_account_key),\n",
    "                azure_file_url='https://{0}.file.core.windows.net/{1}'.format(\n",
    "                    cfg.storage_account_name, azure_file_share_name),\n",
    "                relative_mount_path=azure_file_share_mount_path)\n",
    "        ],\n",
    "        azure_blob_file_systems=[\n",
    "            models.AzureBlobFileSystemReference(\n",
    "                account_name=cfg.storage_account_name,\n",
    "                credentials=models.AzureStorageCredentialsInfo(\n",
    "                    account_key=cfg.storage_account_key),\n",
    "                container_name=azure_blob_container_name,\n",
    "                relative_mount_path=azure_blob_mount_path)\n",
    "        ]\n",
    "    ),\n",
    "    container_settings=models.ContainerSettings(\n",
    "        image_source_registry=models.ImageSourceRegistry(image='microsoft/cntk:2.5.1-gpu-python2.7-cuda9.0-cudnn7.0')\n",
    "    ),\n",
    "    cntk_settings=models.CNTKsettings(\n",
    "        python_script_file_path='$AZ_BATCHAI_JOB_MOUNT_ROOT/{0}/{1}/{2}'.format(\n",
    "            azure_file_share_mount_path, script_path, script_name),\n",
    "        command_line_args='--estimators {0} --ngrams {1} --inputs $AZ_BATCHAI_INPUT_SCRIPT --outputs $AZ_BATCHAI_OUTPUT_ALL'\n",
    "            .format(parameters['ESTIMATORS'], parameters['NGRAMS'])  # Substitute hyperparameters\n",
    "    )\n",
    ")"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "Next, we generate a list of jobs to submit."
   ]
  },
  {
   "cell_type": "code",
   "execution_count": 15,
   "metadata": {},
   "outputs": [
    {
     "name": "stdout",
     "output_type": "stream",
     "text": [
      "Parameters 1: {'PARAM_NGRAMS': 1, 'PARAM_ESTIMATORS': 2}\n",
      "Parameters 2: {'PARAM_NGRAMS': 2, 'PARAM_ESTIMATORS': 2}\n"
     ]
    }
   ],
   "source": [
    "# Generate Jobs\n",
    "num_configs = 2\n",
    "jobs_to_submit, param_combinations = parameters.generate_jobs_random_search(jcp, num_configs)\n",
    "\n",
    "# Print the parameter combinations generated\n",
    "for idx, comb in enumerate(param_combinations):\n",
    "    print(\"Parameters {0}: {1}\".format(idx + 1, comb))"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "And we submit the jobs to the experiment."
   ]
  },
  {
   "cell_type": "code",
   "execution_count": 16,
   "metadata": {},
   "outputs": [
    {
     "name": "stdout",
     "output_type": "stream",
     "text": [
      "Initialized JobSubmitter in resource group: maboumlb | workspace: maboumlb | experiment: random_search_experiment\n",
      "Created job \"hyperparam_job_1883dde79c53c99e\" with parameters {\"PARAM_ESTIMATORS\": \"2\", \"PARAM_NGRAMS\": \"2\"}\n",
      "Created job \"hyperparam_job_808f1cac5503f018\" with parameters {\"PARAM_ESTIMATORS\": \"2\", \"PARAM_NGRAMS\": \"1\"}\n"
     ]
    }
   ],
   "source": [
    "experiment_utils = utils.experiment.ExperimentUtils(client, cfg.resource_group, cfg.workspace, experiment_name)\n",
    "jobs = experiment_utils.submit_jobs(jobs_to_submit, 'hyperparam_job').result()"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "Wait for all the jobs to complete."
   ]
  },
  {
   "cell_type": "code",
   "execution_count": 17,
   "metadata": {},
   "outputs": [
    {
     "name": "stdout",
     "output_type": "stream",
     "text": [
      "0/2 jobs completed (0 succeeded, 0 failed)...............\n",
      "0/2 jobs completed (0 succeeded, 0 failed)...............\n",
      "0/2 jobs completed (0 succeeded, 0 failed)...............\n",
      "0/2 jobs completed (0 succeeded, 0 failed)...............\n",
      "0/2 jobs completed (0 succeeded, 0 failed)...............\n",
      "0/2 jobs completed (0 succeeded, 0 failed)...............\n",
      "0/2 jobs completed (0 succeeded, 0 failed)...............\n",
      "1/2 jobs completed (0 succeeded, 1 failed)...............\n",
      "1/2 jobs completed (0 succeeded, 1 failed)...............\n",
      "All jobs completed.\n"
     ]
    },
    {
     "data": {
      "text/plain": [
       "[<azure.mgmt.batchai.models.job_py3.Job at 0x7f06eb996f60>,\n",
       " <azure.mgmt.batchai.models.job_py3.Job at 0x7f06eb996ef0>]"
      ]
     },
     "execution_count": 17,
     "metadata": {},
     "output_type": "execute_result"
    }
   ],
   "source": [
    "experiment_utils.wait_all_jobs()"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "We define the following metric extractor to extract desired metric from learning log file. \n",
    "- In this example, we extract the number between \"metric =\" and \"%\"."
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {},
   "outputs": [],
   "source": [
    "metric_extractor = utils.job.MetricExtractor(\n",
    "                        output_dir_id='ALL',\n",
    "                        logfile='progress.log',\n",
    "                        regex='metric =(.*?)\\%')"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "We wait on the jobs the finish, then get the metric value from the log files of the finished jobs."
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {},
   "outputs": [],
   "source": [
    "# Wait for all jobs to complete\n",
    "experiment_utils.wait_all_jobs()\n",
    "\n",
    "# Get the metrics from the jobs\n",
    "results = experiment_utils.get_metrics_for_jobs(jobs, metric_extractor)\n",
    "results.sort(key=lambda r: r['metric_value'])\n",
    "\n",
    "# Print results\n",
    "for result in results:\n",
    "    print(\"Job {0} completed with metric value {1}\".format(result['job_name'], result['metric_value']))\n",
    "print(\"Best job: {0} with parameters {1}\".format(\n",
    "    results[0]['job_name'], \n",
    "    {ev.name:ev.value for ev in results[0]['job'].environment_variables}\n",
    "))"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "## 4. Clean Up (Optional)"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "### Delete the Experiment\n",
    "Delete the experiment and jobs inside it"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {},
   "outputs": [],
   "source": [
    "_ = client.experiments.delete(cfg.resource_group, cfg.workspace, experiment_name).result()"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "### Delete the Cluster\n",
    "When you are finished with the sample and don't want to submit any more jobs you can delete the cluster using the following code."
   ]
  },
  {
   "cell_type": "code",
   "execution_count": 12,
   "metadata": {},
   "outputs": [],
   "source": [
    "_ = client.clusters.delete(cfg.resource_group, cfg.workspace, cluster_name).result()"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {
    "collapsed": true
   },
   "source": [
    "### Delete File Share\n",
    "When you are finished with the sample and don't want to submit any more jobs you can delete the file share completely with all files using the following code."
   ]
  },
  {
   "cell_type": "code",
   "execution_count": 13,
   "metadata": {},
   "outputs": [
    {
     "data": {
      "text/plain": [
       "True"
      ]
     },
     "execution_count": 13,
     "metadata": {},
     "output_type": "execute_result"
    }
   ],
   "source": [
    "service = FileService(cfg.storage_account_name, cfg.storage_account_key)\n",
    "service.delete_share(azure_file_share_name)"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {},
   "outputs": [],
   "source": []
  }
 ],
 "metadata": {
  "anaconda-cloud": {},
  "kernelspec": {
   "display_name": "Python [conda env:MLBatchAIHyperparameterTuning]",
   "language": "python",
   "name": "conda-env-MLBatchAIHyperparameterTuning-py"
  },
  "language_info": {
   "codemirror_mode": {
    "name": "ipython",
    "version": 3
   },
   "file_extension": ".py",
   "mimetype": "text/x-python",
   "name": "python",
   "nbconvert_exporter": "python",
   "pygments_lexer": "ipython3",
   "version": "3.5.5"
  }
 },
 "nbformat": 4,
 "nbformat_minor": 1
}