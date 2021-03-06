# Copyright 2015 Paul Balanca. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Pre-processing images 
"""
import numpy as np

import tensorflow as tf
import tf_extended as tfe

from tensorflow.python.ops import control_flow_ops

from preprocessing import tf_image

slim = tf.contrib.slim

# Resizing strategies.
class Resize():
    NONE = 0;          # Nothing!
    CENTRAL_CROP = 1;               # Crop (and pad if necessary).
    PAD_AND_RESIZE = 2;           # Pad, and resize to output shape.
    WARP_RESIZE = 3;        # Warp resize.


# Some training pre-processing parameters.
BBOX_CROP_OVERLAP = 0.1        # Minimum overlap to keep a bbox after cropping.
CROP_RATIO_RANGE = (0.8, 1.2)  # Distortion ratio during cropping.




def tf_summary_image(image, bboxes = None, name='image'):
    """Add image with bounding boxes to summary.
    """
    if (len(image.shape) == 2):
        image = tf.cast(image, tf.float32);
        image = tf.expand_dims(image, 0);
        image = tf.transpose(image, [1, 2, 0]);        
    
    image = tf.expand_dims(image, 0)
    
    if bboxes is not None:
        if len(bboxes.shape) == 2:
            bboxes = tf.expand_dims(bboxes, 0);
        image = tf.image.draw_bounding_boxes(image, bboxes)
    tf.summary.image(name, image)


def apply_with_random_selector(x, func, num_cases):
    """Computes func(x, sel), with sel sampled from [0...num_cases-1].

    Args:
        x: input Tensor.
        func: Python function to apply.
        num_cases: Python int32, number of cases to sample sel from.

    Returns:
        The result of func(x, sel), where func receives the value of the
        selector as a python integer, but sel is sampled dynamically.
    """
    sel = tf.random_uniform([], maxval=num_cases, dtype=tf.int32)
    # Pass the real x only to one of the func calls.
    return control_flow_ops.merge([
            func(control_flow_ops.switch(x, tf.equal(sel, case))[1], case)
            for case in range(num_cases)])[0]


def distort_color(image, color_ordering=0, fast_mode=True, scope=None):
    """Distort the color of a Tensor image.

    Each color distortion is non-commutative and thus ordering of the color ops
    matters. Ideally we would randomly permute the ordering of the color ops.
    Rather then adding that level of complication, we select a distinct ordering
    of color ops for each preprocessing thread.

    Args:
        image: 3-D Tensor containing single image in [0, 1].
        color_ordering: Python int, a type of distortion (valid values: 0-3).
        fast_mode: Avoids slower ops (random_hue and random_contrast)
        scope: Optional scope for name_scope.
    Returns:
        3-D Tensor color-distorted image on range [0, 1]
    Raises:
        ValueError: if color_ordering not in [0, 3]
    """
    with tf.name_scope(scope, 'distort_color', [image]):
        if fast_mode:
            if color_ordering == 0:
                image = tf.image.random_brightness(image, max_delta=32.)
                image = tf.image.random_saturation(image, lower=0.5, upper=1.5)
            else:
                image = tf.image.random_saturation(image, lower=0.5, upper=1.5)
                image = tf.image.random_brightness(image, max_delta=32.)
        else:
            if color_ordering == 0:
                image = tf.image.random_brightness(image, max_delta=32.)
                image = tf.image.random_saturation(image, lower=0.5, upper=1.5)
                image = tf.image.random_hue(image, max_delta=0.2)
                image = tf.image.random_contrast(image, lower=0.5, upper=1.5)
            elif color_ordering == 1:
                image = tf.image.random_saturation(image, lower=0.5, upper=1.5)
                image = tf.image.random_brightness(image, max_delta=32.)
                image = tf.image.random_contrast(image, lower=0.5, upper=1.5)
                image = tf.image.random_hue(image, max_delta=0.2)
            elif color_ordering == 2:
                image = tf.image.random_contrast(image, lower=0.5, upper=1.5)
                image = tf.image.random_hue(image, max_delta=0.2)
                image = tf.image.random_brightness(image, max_delta=32.)
                image = tf.image.random_saturation(image, lower=0.5, upper=1.5)
            elif color_ordering == 3:
                image = tf.image.random_hue(image, max_delta=0.2)
                image = tf.image.random_saturation(image, lower=0.5, upper=1.5)
                image = tf.image.random_contrast(image, lower=0.5, upper=1.5)
                image = tf.image.random_brightness(image, max_delta=32.)
            else:
                raise ValueError('color_ordering must be in [0, 3]')
        # The random_* ops do not necessarily clamp.
        return tf.clip_by_value(image, 0.0, 255.0)


def distorted_bounding_box_crop(image,
                                labels,
                                bboxes,
                                min_object_covered= 0.9,
                                aspect_ratio_range=(0.2, 1.1),
                                area_range=(0.1, 1.0),
                                max_attempts=500,
                                scope=None):
    """Generates cropped_image using a one of the bboxes randomly distorted.

    See `tf.image.sample_distorted_bounding_box` for more documentation.

    Args:
        image: 3-D Tensor of image (it will be converted to floats in [0, 1]).
        bbox: 3-D float Tensor of bounding boxes arranged [1, num_boxes, coords]
            where each coordinate is [0, 1) and the coordinates are arranged
            as [ymin, xmin, ymax, xmax]. If num_boxes is 0 then it would use the whole
            image.
        min_object_covered: An optional `float`. Defaults to `0.1`. The cropped
            area of the image must contain at least this fraction of any bounding box
            supplied.
        aspect_ratio_range: An optional list of `floats`. The cropped area of the
            image must have an aspect ratio = width / height within this range.
        area_range: An optional list of `floats`. The cropped area of the image
            must contain a fraction of the supplied image within in this range.
        max_attempts: An optional `int`. Number of attempts at generating a cropped
            region of the image of the specified constraints. After `max_attempts`
            failures, return the entire image.
        scope: Optional scope for name_scope.
    Returns:
        A tuple, a 3-D Tensor cropped_image and the distorted bbox
    """
    with tf.name_scope(scope, 'distorted_bounding_box_crop', [image, bboxes]):
        # Each bounding box has shape [1, num_boxes, box coords] and
        # the coordinates are ordered [ymin, xmin, ymax, xmax].
        bbox_begin, bbox_size, distort_bbox = tf.image.sample_distorted_bounding_box(
                tf.shape(image),
                bounding_boxes=bboxes, #tf.expand_dims(bboxes, 0),
                min_object_covered=min_object_covered,
                aspect_ratio_range=aspect_ratio_range,
                area_range=area_range,
                max_attempts=max_attempts,
                use_image_if_no_bounding_boxes=False)
        distort_bbox = distort_bbox[0, 0]

        # Crop the image to the specified bounding box.
        cropped_image = tf.slice(image, bbox_begin, bbox_size)
        # Restore the shape since the dynamic slice loses 3rd dimension.
        cropped_image.set_shape([None, None, 3])

        # Update bounding boxes: resize and filter out.
        bboxes = tfe.bboxes_resize(distort_bbox, bboxes)
        labels, bboxes = tfe.bboxes_filter_overlap(labels, bboxes, BBOX_CROP_OVERLAP)
        return cropped_image, labels, bboxes, distort_bbox


def preprocess_for_train(image, labels, bboxes,
                         out_shape, data_format='NHWC',
                         scope='preprocessing_train'):
    """Preprocesses the given image for training.

    Note that the actual resizing scale is sampled from
        [`resize_size_min`, `resize_size_max`].

    Args:
        image: A `Tensor` representing an image of arbitrary size.
        output_height: The height of the image after preprocessing.
        output_width: The width of the image after preprocessing.
        resize_side_min: The lower bound for the smallest side of the image for
            aspect-preserving resizing.
        resize_side_max: The upper bound for the smallest side of the image for
            aspect-preserving resizing.

    Returns:
        A preprocessed image.
    """
    fast_mode = False
    with tf.name_scope(scope, 'preprocessing_train', [image, labels, bboxes]):
#        if image.get_shape().ndims != 3:
#            raise ValueError('Input must be of size [height, width, C>0]')
        # Convert to float scaled [0, 1].
        if image.dtype != tf.float32:
            image = tf.image.convert_image_dtype(image, dtype=tf.float32)
        #tf_summary_image(image, bboxes, 'image_with_bboxes')

        # Distort image and bounding boxes.
        dst_image = image
        dst_image, labels, bboxes, distort_bbox = distorted_bounding_box_crop(image, labels, bboxes, aspect_ratio_range=CROP_RATIO_RANGE)
        # Resize image to output size.
        dst_image = tf_image.resize_image(dst_image, out_shape, method=tf.image.ResizeMethod.BILINEAR, align_corners=False)
        #tf_summary_image(dst_image, bboxes, 'image_shape_distorted')

        # Randomly flip the image horizontally.
        dst_image, bboxes = tf_image.random_flip_left_right(dst_image, bboxes)
        
        # Randomly distort the colors. There are 4 ways to do it.
        dst_image = apply_with_random_selector(
                dst_image,
                lambda x, ordering: distort_color(x, ordering, fast_mode),
                num_cases=4)
        #tf_summary_image(dst_image, bboxes, 'image_color_distorted')
        # Rescale to VGG input scale.
        image = dst_image * 255
#        image = tf_image_whitened(image, [_R_MEAN, _G_MEAN, _B_MEAN])
        # Image data format.
        if data_format == 'NCHW':
            image = tf.transpose(image, perm=(2, 0, 1))
        
        i = tf.constant(0)
        n_rows = tf.size(bboxes) / 4;
        while_condition = lambda i, m: tf.less(i, n_rows)
        
        h, w = out_shape[0], out_shape[1]
        mask = tf.zeros(out_shape, dtype = "int32");
        def body(i, mask):
            
            bbox = bboxes[i];
            min_y = tf.cast(bbox[0] * h, dtype=tf.int32)
            max_y = tf.cast(bbox[2] * h, dtype=tf.int32)
            min_x = tf.cast(bbox[1] * w, dtype=tf.int32)
            max_x = tf.cast(bbox[3] * w, dtype=tf.int32)
            min_y = tf.cond(min_y > 0, lambda:min_y, lambda:tf.constant(0))
            max_y = tf.cond(max_y < h, lambda:max_y, lambda:tf.constant(h))
            min_x = tf.cond(min_x > 0, lambda:min_x, lambda:tf.constant(0));
            max_x = tf.cond(max_x < w, lambda:max_x, lambda:tf.constant(w));
            temp = tf.cast(tf.stack([max_y - min_y, max_x - min_x]), dtype=tf.int32)
            ones = tf.ones(temp, tf.float32)
            
            temp = tf.cast(tf.stack([min_y, out_shape[0] - max_y, min_x, out_shape[1]- max_x]), tf.int32)
            temp = tf.reshape(temp, (2, 2))
            bbox_mask = tf.cast(tf.pad(ones, temp, "CONSTANT"), dtype=tf.int32)
            
            mask = mask + bbox_mask
            return [i+1, mask];
        _, mask = tf.while_loop(while_condition, body, [i, mask], back_prop=False)
#        mask = tf.Variable
        mask = tf.greater(mask, tf.zeros(out_shape, dtype = "int32"));
        mask = tf.cast(mask, dtype = tf.int32);
        #mask0 = tf.ones(out_shape, dtype = "int32") - mask;
        #mask = tf.stack([mask0, mask]);
        #mask = tf.transpose(mask, (1, 2, 0));
#        tf_summary_image(mask, name = 'label')
#        tf_summary_image(image, bboxes = bboxes, name = 'image');
        return image, mask, bboxes



def preprocess_image(image,
                     labels,
                     bboxes,
                     out_shape,
                     data_format,
                     is_training=False,
                     **kwargs):
    """Pre-process an given image.

    Args:
      image: A `Tensor` representing an image of arbitrary size.
      output_height: The height of the image after preprocessing.
      output_width: The width of the image after preprocessing.
      is_training: `True` if we're preprocessing the image for training and
        `False` otherwise.
      resize_side_min: The lower bound for the smallest side of the image for
        aspect-preserving resizing. If `is_training` is `False`, then this value
        is used for rescaling.
      resize_side_max: The upper bound for the smallest side of the image for
        aspect-preserving resizing. If `is_training` is `False`, this value is
         ignored. Otherwise, the resize side is sampled from
         [resize_size_min, resize_size_max].

    Returns:
      A preprocessed image.
    """
    return preprocess_for_train(image, labels, bboxes,
                                    out_shape=out_shape,
                                    data_format=data_format)
