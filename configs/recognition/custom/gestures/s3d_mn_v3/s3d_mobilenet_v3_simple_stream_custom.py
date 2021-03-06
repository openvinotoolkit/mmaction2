# global parameters
num_videos_per_gpu = 12
num_workers_per_gpu = 3
train_sources = 'common_selfcreated',
test_sources = 'common_selfcreated',

root_dir = 'data'
work_dir = None
load_from = None
resume_from = None

# model settings
input_clip_length = 8
input_img_size = 224
reset_layer_prefixes = ['cls_head']
reset_layer_suffixes = None

# model definition
model = dict(
    type='Recognizer3D',
    backbone=dict(
        type='MobileNetV3_S3D',
        num_input_layers=3,
        mode='large',
        pretrained=None,
        pretrained2d=False,
        width_mult=1.0,
        pool1_stride_t=1,
        # block ids:      0  1  2  3  4  5  6  7  8  9  10 11 12 13 14
        temporal_strides=(1, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1),
        temporal_kernels=(5, 3, 3, 3, 3, 5, 5, 3, 3, 5, 3, 3, 3, 3, 3),
        use_temporal_avg_pool=True,
        input_bn=False,
        out_conv=True,
        out_attention=False,
        weight_norm='none',
        center_conv_weight=None,
        dropout_cfg=dict(
            dist='gaussian',
            p=0.1,
            mu=0.1,
            sigma=0.03,
        ),
    ),
    reducer=dict(
        type='AggregatorSpatialTemporalModule',
        modules=[
            dict(type='AverageSpatialTemporalModule',
                 temporal_size=4,
                 spatial_size=7),
        ],
    ),
    cls_head=dict(
        type='ClsHead',
        num_classes=12,
        temporal_size=1,
        spatial_size=1,
        dropout_ratio=None,
        in_channels=960,
        embedding=False,
        loss_cls=dict(
            type='CrossEntropyLoss',
            loss_weight=1.0
        ),
    ),
)

# model training and testing settings
train_cfg = dict(
    self_challenging=dict(enable=False, drop_p=0.33),
    clip_mixing=dict(enable=False, mode='logits', weight=0.2)
)
test_cfg = dict(
    average_clips=None
)

# dataset settings
img_norm_cfg = dict(
    mean=[123.675, 116.28, 103.53],
    std=[58.395, 57.12, 57.375],
    to_bgr=False
)
train_pipeline = [
    dict(type='StreamSampleFrames',
         clip_len=input_clip_length,
         trg_fps=15,
         num_clips=2,
         temporal_jitter=True,
         min_intersection=1.0),
    dict(type='RawFrameDecode'),
    dict(type='Resize', scale=(-1, 256)),
    dict(type='RandomRotate', delta=10, prob=0.5),
    dict(type='RatioPreservingCrop',
         input_size=input_img_size, scale_limits=(1, 0.875)),
    dict(type='Flip', flip_ratio=0.5),
    dict(type='MapFlippedLabels', map_file=dict(jester='flip_labels_map.txt')),
    dict(type='PhotometricDistortion',
         brightness_range=(65, 190),
         contrast_range=(0.6, 1.4),
         saturation_range=(0.7, 1.3),
         hue_delta=18),
    dict(type='Normalize', **img_norm_cfg),
    dict(type='FormatShape', input_format='NCTHW', targets=['imgs']),
    dict(type='Collect', keys=['imgs', 'label', 'dataset_id'], meta_keys=[]),
    dict(type='ToTensor', keys=['imgs', 'label', 'dataset_id'])
]
val_pipeline = [
    dict(type='StreamSampleFrames',
         clip_len=input_clip_length,
         trg_fps=15,
         num_clips=1,
         test_mode=True),
    dict(type='RawFrameDecode'),
    dict(type='Resize', scale=(-1, 256)),
    dict(type='CenterCrop', crop_size=input_img_size),
    dict(type='Normalize', **img_norm_cfg),
    dict(type='FormatShape', input_format='NCTHW'),
    dict(type='Collect', keys=['imgs'], meta_keys=[]),
    dict(type='ToTensor', keys=['imgs'])
]
data = dict(
    videos_per_gpu=num_videos_per_gpu,
    workers_per_gpu=num_workers_per_gpu,
    train_dataloader=dict(
        drop_last=True
    ),
    shared=dict(
        type='RawframeDataset',
        data_subdir='global_crops',
        filename_tmpl='{:05d}.jpg'
    ),
    train=dict(
        source=train_sources,
        ann_file='train.txt',
        pipeline=train_pipeline,
    ),
    val=dict(
        source=test_sources,
        ann_file='test.txt',
        pipeline=val_pipeline
    ),
    test=dict(
        source=test_sources,
        ann_file='test.txt',
        pipeline=val_pipeline
    )
)

# optimizer
optimizer = dict(
    type='SGD',
    lr=1e-3,
    momentum=0.9,
    weight_decay=1e-4
)
optimizer_config = dict(
    grad_clip=dict(
        max_norm=40,
        norm_type=2
    )
)

# parameter manager
params_config = dict(
    type='FreezeLayers',
    epochs=5,
    open_layers=['cls_head']
)

# learning policy
lr_config = dict(
    policy='customstep',
    step=[30, 50],
    gamma=0.1,
    fixed='constant',
    fixed_epochs=5,
    fixed_ratio=10.0,
    warmup='linear',
    warmup_epochs=5,
    warmup_ratio=1e-2,
)
total_epochs = 65

# workflow
workflow = [('train', 1)]
checkpoint_config = dict(
    interval=1
)
evaluation = dict(
    interval=1,
    metrics=['top_k_accuracy', 'mean_class_accuracy', 'ranking_mean_average_precision'],
    topk=(1, 5),
)

log_level = 'INFO'
log_config = dict(
    interval=10,
    hooks=[
        dict(type='TextLoggerHook'),
        dict(type='TensorboardLoggerHook'),
    ]
)

# runtime settings
dist_params = dict(
    backend='nccl'
)
find_unused_parameters = True
