import copy
import os
import os.path as osp

import mmcv
import numpy as np

from ..core import average_recall_at_avg_proposals
from .base import BaseDataset
from .registry import DATASETS


@DATASETS.register_module()
class ActivityNetDataset(BaseDataset):
    """ActivityNet dataset for temporal action localization.

    The dataset loads raw features and apply specified transforms to return a
    dict containing the frame tensors and other information.

    The ann_file is a json file with multiple objects, and each object has a
    key of the name of a video, and value of total frames of the video, total
    seconds of the video, annotations of a video, feature frames (frames
    covered by features) of the video, fps and rfps. Example of a
    annotation file:

    .. code-block:: JSON

        {
            "v_--1DO2V4K74":  {
                "duration_second": 211.53,
                "duration_frame": 6337,
                "annotations": [
                    {
                        "segment": [
                            30.025882995319815,
                            205.2318595943838
                        ],
                        "label": "Rock climbing"
                    }
                ],
                "feature_frame": 6336,
                "fps": 30.0,
                "rfps": 29.9579255898
            },
            "v_--6bJUbfpnQ": {
                "duration_second": 26.75,
                "duration_frame": 647,
                "annotations": [
                    {
                        "segment": [
                            2.578755070202808,
                            24.914101404056165
                        ],
                        "label": "Drinking beer"
                    }
                ],
                "feature_frame": 624,
                "fps": 24.0,
                "rfps": 24.1869158879
            },
            ...
        }


    Args:
        ann_file (str): Path to the annotation file.
        pipeline (list[dict | callable]): A sequence of data transforms.
        data_prefix (str): Path to a directory where videos are held.
            Default: None.
        test_mode (bool): Store True when building test or validation dataset.
            Default: False.
    """

    allowed_metrics = ['AR@AN']

    def __init__(self,
                 source,
                 root_dir,
                 ann_file,
                 data_subdir,
                 pipeline,
                 test_mode=False,
                 logger=None):
        super().__init__(source, root_dir, ann_file, data_subdir, pipeline,
                         test_mode=test_mode, logger=logger)

    def _load_annotations(self, ann_file, data_prefix=None):
        """Load the annotation according to ann_file into video_infos."""
        video_infos = []
        anno_database = mmcv.load(ann_file)
        for video_name in anno_database:
            video_info = anno_database[video_name]
            video_info['video_name'] = video_name
            video_info['data_prefix'] = data_prefix
            video_infos.append(video_info)
        return video_infos

    def prepare_test_frames(self, idx):
        """Prepare the frames for testing given the index."""
        results = copy.deepcopy(self.records[idx])
        return self.pipeline(results)

    def prepare_train_frames(self, idx):
        """Prepare the frames for training given the index."""
        results = copy.deepcopy(self.records[idx])
        return self.pipeline(results)

    def __len__(self):
        """Get the size of the dataset."""
        return len(self.records)

    def _import_ground_truth(self):
        """Read ground truth data from video_infos."""
        ground_truth = {}
        for video_info in self.records:
            video_id = video_info['video_name'][2:]
            this_video_ground_truths = []
            for ann in video_info['annotations']:
                t_start, t_end = ann['segment']
                label = ann['label']
                this_video_ground_truths.append([t_start, t_end, label])
            ground_truth[video_id] = np.array(this_video_ground_truths)
        return ground_truth

    def proposals2json(self, results, show_progress=False):
        """Convert all proposals to a final dict(json) format.

        Args:
            results (list[dict]): All proposals.
            show_progress (bool): Whether to show the progress bar.
                Defaults: False.

        Returns:
            dict: The final result dict. E.g.

            .. code-block:: Python

                dict(video-1=[dict(segment=[1.1,2.0]. score=0.9),
                              dict(segment=[50.1, 129.3], score=0.6)])
        """
        result_dict = {}
        print('Convert proposals to json format')
        if show_progress:
            prog_bar = mmcv.ProgressBar(len(results))
        for result in results:
            video_name = result['video_name']
            result_dict[video_name[2:]] = result['proposal_list']
            if show_progress:
                prog_bar.update()
        return result_dict

    def _import_proposals(self, results):
        """Read predictions from results."""
        proposals = {}
        num_proposals = 0
        for result in results:
            video_id = result['video_name'][2:]
            this_video_proposals = []
            for proposal in result['proposal_list']:
                t_start, t_end = proposal['segment']
                score = proposal['score']
                this_video_proposals.append([t_start, t_end, score])
                num_proposals += 1
            proposals[video_id] = np.array(this_video_proposals)
        return proposals, num_proposals

    def dump_results(self, results, out, output_format, version='VERSION 1.3'):
        """Dump data to json/csv files."""
        if output_format == 'json':
            result_dict = self.proposals2json(results)
            output_dict = {
                'version': version,
                'results': result_dict,
                'external_data': {}
            }
            mmcv.dump(output_dict, out)
        elif output_format == 'csv':
            # TODO: add csv handler to mmcv and use mmcv.dump
            os.makedirs(out, exist_ok=True)
            header = 'action,start,end,tmin,tmax'
            for result in results:
                video_name, outputs = result
                output_path = osp.join(out, video_name + '.csv')
                np.savetxt(
                    output_path,
                    outputs,
                    header=header,
                    delimiter=',',
                    comments='')
        else:
            raise ValueError(
                f'The output format {output_format} is not supported.')

    def _evaluate(self,
                  results,
                  metrics='AR@AN',
                  max_avg_proposals=100,
                  temporal_iou_thresholds=np.linspace(0.5, 0.95, 10),
                  logger=None):
        """Evaluation in feature dataset.

        Args:
            results (list[dict]): Output results.
            metrics (str | sequence[str]): Metrics to be performed.
                Defaults: 'AR@AN'.
            max_avg_proposals (int): Max number of proposals to evaluate.
                Defaults: 100.
            temporal_iou_thresholds (list): Temporal IoU threshold for positive
                samples. Defaults: np.linspace(0.5, 0.95, 10).
            logger (logging.Logger | None): Training logger. Defaults: None.

        Returns:
            dict: Evaluation results for evaluation metrics.
        """

        eval_results = {}
        ground_truth = self._import_ground_truth()
        proposal, num_proposals = self._import_proposals(results)

        for metric in metrics:
            if metric == 'AR@AN':
                recall, _, _, auc = (
                    average_recall_at_avg_proposals(
                        ground_truth,
                        proposal,
                        num_proposals,
                        max_avg_proposals=max_avg_proposals,
                        temporal_iou_thresholds=temporal_iou_thresholds))
                eval_results['auc'] = auc
                eval_results['AR@1'] = np.mean(recall[:, 0])
                eval_results['AR@5'] = np.mean(recall[:, 4])
                eval_results['AR@10'] = np.mean(recall[:, 9])
                eval_results['AR@100'] = np.mean(recall[:, 99])

        return eval_results
